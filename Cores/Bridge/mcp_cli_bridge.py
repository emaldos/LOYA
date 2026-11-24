"""stdio <-> LOYA MCP bridge for the operator's OWN Claude Code / Codex CLI (Settings > AI > Agents > Connections).

The CLI starts this script as a stdio MCP server (registered with `claude mcp add` / `codex mcp add`). It forwards every
JSON-RPC message, unchanged, to LOYA's in-app MCP server (streamable HTTP on 127.0.0.1) with the connection's bearer
token, and writes the replies back to stdout. So the CLI talks to the same server, with the same AI Roles checks,
approval prompts, lock and secret redaction as every other LOYA client; LOYA tells which CLI made a call from the token.

The token and port are read from the connection file LOYA wrote (--token-file); nothing secret is on the command line or
in the CLI's own config, and Disconnect deletes the file, which revokes the bridge at once.

Standard library only, so it also runs with -I (isolated mode) and does not import anything from the working folder.
`--selftest` does initialize + tools/list and prints one JSON line (used by "Test connection").
"""
import json,os,sys,threading,urllib.request,urllib.error
NOT_RUNNING=("LOYA NG is not running, or its MCP server is off. Open LOYA NG (and unlock it); the server starts on its own "
             "while a CLI is connected. Otherwise reconnect under Settings > AI > Agents > Connections.")
TIMEOUT=600  # a tool call can wait for the operator's approval in the app (up to a few minutes)
class Bridge:
    def __init__(self,token_file,port=None):
        self.token_file=token_file
        self.port_override=port
        self.session=None
        self.protocol=None
        self.out_lock=threading.Lock()
        self.cfg={}
        self.load()
    def load(self):
        try:
            with open(self.token_file,"r",encoding="utf-8") as f:d=json.load(f)
            self.cfg=d if isinstance(d,dict) else {}
        except Exception:
            self.cfg={}
    @property
    def url(self):
        port=self.port_override or self.cfg.get("port") or 8765
        return f"http://127.0.0.1:{int(port)}/mcp"
    def write(self,obj):
        data=(json.dumps(obj,ensure_ascii=False,separators=(",",":"))+"\n").encode("utf-8")
        with self.out_lock:
            sys.stdout.buffer.write(data)
            sys.stdout.buffer.flush()
    def error(self,msg_id,message,code=-32000):
        if msg_id is None:return
        self.write({"jsonrpc":"2.0","id":msg_id,"error":{"code":code,"message":message}})
    def _request(self,body,method="POST"):
        tok=str(self.cfg.get("token") or "")
        if not tok:raise PermissionError("This CLI is not connected to LOYA NG any more (no connection token). Connect it again under Settings > AI > Agents > Connections.")
        headers={"Content-Type":"application/json","Accept":"application/json, text/event-stream","Authorization":"Bearer "+tok}
        if self.session:headers["Mcp-Session-Id"]=self.session
        if self.protocol:headers["MCP-Protocol-Version"]=self.protocol
        req=urllib.request.Request(self.url,data=None if body is None else json.dumps(body).encode("utf-8"),method=method,headers=headers)
        return urllib.request.urlopen(req,timeout=TIMEOUT)
    def _messages(self,resp):
        """The JSON-RPC messages in one HTTP reply: a JSON body, or a server-sent event stream read as it arrives."""
        ctype=(resp.headers.get("Content-Type") or "").lower()
        if "text/event-stream" in ctype:
            data=[]
            for raw in resp:
                line=raw.decode("utf-8","replace").rstrip("\r\n")
                if line.startswith("data:"):data.append(line[5:].lstrip(" "))
                elif line=="" and data:
                    try:yield json.loads("\n".join(data))
                    except Exception:pass
                    data=[]
            if data:
                try:yield json.loads("\n".join(data))
                except Exception:pass
            return
        body=resp.read()
        if not body.strip():return
        obj=json.loads(body.decode("utf-8","replace"))
        for m in (obj if isinstance(obj,list) else [obj]):yield m
    def forward(self,msg,collect=None):
        msg_id=msg.get("id") if isinstance(msg,dict) else None
        if isinstance(msg,dict) and "method" not in msg:msg_id=None  # a reply from the CLI: nothing to answer
        for attempt in (0,1):
            try:
                with self._request(msg) as resp:
                    if isinstance(msg,dict) and msg.get("method")=="initialize":
                        self.session=resp.headers.get("Mcp-Session-Id") or self.session
                    for m in self._messages(resp):
                        if isinstance(msg,dict) and msg.get("method")=="initialize" and isinstance(m,dict):
                            self.protocol=((m.get("result") or {}).get("protocolVersion")) or self.protocol
                        if collect is not None:collect.append(m)
                        else:self.write(m)
                return True
            except urllib.error.HTTPError as e:
                try:detail=json.loads(e.read().decode("utf-8","replace")).get("error")
                except Exception:detail=""
                if e.code==401 and attempt==0:
                    self.load();continue  # reconnected meanwhile: the file holds a new token
                if e.code==401:self.error(msg_id,"LOYA NG refused this CLI's token. Connect it again under Settings > AI > Agents > Connections.");return False
                if e.code==423:self.error(msg_id,"LOYA NG is locked. Unlock the app before using its tools.");return False
                if e.code==404 and self.session:
                    self.session=None;self.error(msg_id,"The LOYA session ended (the app or its MCP server restarted). Reconnect the MCP server in your CLI (for example /mcp).");return False
                self.error(msg_id,f"LOYA MCP server answered HTTP {e.code}"+(f": {detail}" if detail else "."));return False
            except PermissionError as e:
                self.error(msg_id,str(e));return False
            except (urllib.error.URLError,ConnectionError,OSError,TimeoutError):
                self.error(msg_id,NOT_RUNNING);return False
            except Exception as e:
                self.error(msg_id,f"LOYA bridge error: {type(e).__name__}");return False
        return False
    def close(self):
        if not self.session:return
        try:self._request(None,method="DELETE").close()
        except Exception:pass
    def serve(self):
        threads=[]
        for raw in sys.stdin.buffer:
            line=raw.decode("utf-8","replace").strip()
            if not line:continue
            try:msg=json.loads(line)
            except Exception:
                self.write({"jsonrpc":"2.0","id":None,"error":{"code":-32700,"message":"Parse error"}});continue
            if isinstance(msg,dict) and msg.get("method")=="initialize":
                self.forward(msg)  # in order: later messages need its session id
                continue
            t=threading.Thread(target=self.forward,args=(msg,),daemon=True)
            t.start();threads.append(t)
            threads=[x for x in threads if x.is_alive()]
        for t in threads:t.join(timeout=5)
        self.close()
    def selftest(self):
        out=[]
        init={"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"loya-bridge-selftest","version":"1"}}}
        errors=[]
        self.error=lambda msg_id,message,code=-32000:errors.append(message)
        if not self.forward(init,out) or not out or "result" not in out[-1]:
            return {"ok":False,"error":errors[0] if errors else "No answer to initialize."}
        server=((out[-1]["result"].get("serverInfo") or {}).get("name")) or ""
        self.forward({"jsonrpc":"2.0","method":"notifications/initialized"},[])
        out=[]
        if not self.forward({"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}},out) or not out or "result" not in out[-1]:
            self.close()
            return {"ok":False,"error":errors[0] if errors else "No answer to tools/list."}
        n=len(out[-1]["result"].get("tools") or [])
        self.close()
        return {"ok":True,"server":server,"tools":n}
def _arg(argv,name,default=None):
    if name in argv:
        i=argv.index(name)
        if i+1<len(argv):return argv[i+1]
    return default
def main(argv=None):
    argv=list(sys.argv[1:] if argv is None else argv)
    token_file=_arg(argv,"--token-file") or os.environ.get("LOYA_CONNECTION_FILE","")
    port=_arg(argv,"--port")
    b=Bridge(token_file,int(port) if port and str(port).isdigit() else None)
    if "--selftest" in argv:
        r=b.selftest()
        sys.stdout.write(json.dumps(r)+"\n");sys.stdout.flush()
        return 0 if r.get("ok") else 1
    try:b.serve()
    except KeyboardInterrupt:pass
    return 0
if __name__=="__main__":
    sys.exit(main())
