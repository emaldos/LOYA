import asyncio,json,os,threading,time,unittest
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from _isolate import IsolatedData
from Cores.Services import ai_service as ai
from Cores.Services import ai_chat_service as chat
from Cores.Services import mcp_local_service as mcp_local
from Cores.Services import terminal_service as terminal
class FakeProvider(BaseHTTPRequestHandler):
    requests=[]
    mode="ok"
    def log_message(self,*a):pass
    def _json(self,obj,code=200):
        raw=json.dumps(obj).encode()
        self.send_response(code);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(raw)));self.end_headers();self.wfile.write(raw)
    def _sse(self,events):
        self.send_response(200);self.send_header("Content-Type","text/event-stream");self.end_headers()
        for e in events:self.wfile.write(("data: "+json.dumps(e)+"\n\n").encode())
    def do_GET(self):
        if self.path=="/api/tags":return self._json({"models":[{"name":"fake:1b"}]})
        self._json({},404)
    def do_POST(self):
        body=json.loads(self.rfile.read(int(self.headers.get("Content-Length",0))) or b"{}")
        FakeProvider.requests.append((self.path,body))
        msgs=body.get("messages",[])
        if FakeProvider.mode=="auth":return self._json({"type":"error","error":{"type":"authentication_error","message":"invalid x-api-key"}},401)
        if self.path=="/v1/chat/completions":
            if "tools" in body and FakeProvider.mode=="notools":return self._json({"error":{"message":"registry.ollama.ai/library/gemma2 does not support tools"}},400)
            return self._sse([{"choices":[{"delta":{"content":"plain answer"}}]}])
        if self.path=="/v1/messages":
            had_result=any(isinstance(m.get("content"),list) and any(b.get("type")=="tool_result" for b in m["content"]) for m in msgs)
            if had_result:return self._sse([{"type":"content_block_start","index":0,"content_block":{"type":"text","text":""}},{"type":"content_block_delta","index":0,"delta":{"type":"text_delta","text":"done"}},{"type":"message_stop"}])
            return self._sse([{"type":"content_block_start","index":0,"content_block":{"type":"thinking","thinking":""}},{"type":"content_block_delta","index":0,"delta":{"type":"thinking_delta","thinking":"let me look"}},{"type":"content_block_delta","index":0,"delta":{"type":"signature_delta","signature":"SIG"}},{"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"tu1","name":"notes_list","input":{}}},{"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{}"}},{"type":"message_stop"}])
        self._json({},404)
class ChatTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.srv=ThreadingHTTPServer(("127.0.0.1",0),FakeProvider)
        threading.Thread(target=cls.srv.serve_forever,daemon=True).start()
        cls.base=f"http://127.0.0.1:{cls.srv.server_address[1]}"
    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown();cls.srv.server_close()
    def setUp(self):
        self.isolated=IsolatedData();self.isolated.start()
        FakeProvider.requests.clear();FakeProvider.mode="ok"
    def tearDown(self):
        self.isolated.stop()
    def test_mcp_is_not_offered_as_a_chat_provider(self):
        ai.set_provider("mcp",{"enabled":True,"url":"http://127.0.0.1:1/mcp"})
        self.assertEqual(ai.enabled_providers(),[])
        with self.assertRaises(ValueError):ai.set_default_provider("mcp")
        with self.assertRaisesRegex(ValueError,"only provides tools"):chat.send_message("mcp",[],"hi")
    def test_anthropic_thinking_blocks_are_replayed_with_the_tool_call(self):
        ai.set_provider("api",{"enabled":True,"provider_kind":"anthropic","api_key":"k-0123456789","base_url":self.base,"model":"m"})
        history=chat.send_message("api",[],"list notes",on_delta=lambda c:None)
        self.assertEqual(history[-1]["content"],"done")
        second=[b for p,b in FakeProvider.requests if p=="/v1/messages"][1]
        assistant=[m for m in second["messages"] if m["role"]=="assistant"][0]
        self.assertEqual(assistant["content"][0],{"type":"thinking","thinking":"let me look","signature":"SIG"})
        self.assertEqual(assistant["content"][-1]["type"],"tool_use")
        self.assertGreaterEqual(second["max_tokens"],4096)
    def test_empty_assistant_turns_are_not_sent_back(self):
        msgs=chat._to_anthropic_messages([{"role":"user","content":"a"},{"role":"assistant","content":""},{"role":"user","content":"b"}])
        self.assertEqual([m["role"] for m in msgs],["user","user"])
    def test_provider_error_body_reaches_the_user(self):
        FakeProvider.mode="auth"
        ai.set_provider("api",{"enabled":True,"provider_kind":"anthropic","api_key":"k-0123456789","base_url":self.base})
        with self.assertRaisesRegex(RuntimeError,"401.*invalid x-api-key"):chat.send_message("api",[],"hi",on_delta=lambda c:None)
    def test_ollama_model_without_tools_still_answers(self):
        FakeProvider.mode="notools"
        host,port=self.base.rsplit(":",1)
        ai.set_provider("ollama",{"enabled":True,"host":"127.0.0.1","port":int(port),"model":"gemma2"})
        history=chat.send_message("ollama",[],"hi",on_delta=lambda c:None)
        self.assertEqual(history[-1]["content"],"plain answer")
        self.assertNotIn("tools",FakeProvider.requests[-1][1])
    def test_bridge_attaches_context_but_shows_what_the_user_typed(self):
        from Cores.Bridge.api import AIAPI,NotesAPI
        from Cores.Services import ai_sessions_service as sessions
        sdir=os.path.join(self.isolated.dir,"ai_sessions");os.makedirs(sdir,exist_ok=True)
        orig=sessions._sessions_dir;sessions._sessions_dir=lambda:sdir
        try:
            nid=NotesAPI().save(None,"Recon plan","Eng","<p>scan the /24 first</p>",[],"recon")["id"]
            host,port=self.base.rsplit(":",1)
            ai.set_provider("ollama",{"enabled":True,"host":"127.0.0.1","port":int(port),"model":"m"})
            api=AIAPI()
            r=api.chat_send_stream_start(None,"ollama","Summarise the attached note",[{"kind":"note","id":nid,"label":"Recon plan"}],"/summarize-note Recon plan")
            for _ in range(200):
                p=api.chat_send_stream_poll(r["session_id"],"ollama",r["stream_id"])
                if p["done"]:break
                time.sleep(0.02)
            self.assertIsNone(p["error"])
            user=[m for m in p["history"] if m["role"]=="user"][0]
            self.assertEqual(user["display"],"/summarize-note Recon plan")
            self.assertEqual(user["attachments"],[{"kind":"note","label":"Recon plan"}])
            sent=[b for path,b in FakeProvider.requests if path=="/v1/chat/completions"][-1]["messages"]
            self.assertIn("scan the /24 first",[m for m in sent if m["role"]=="user"][0]["content"])
            self.assertEqual(sessions.list_sessions()[0]["title"],"/summarize-note Recon plan")
            self.assertEqual(api.complete("reco",["note"],5)[0]["label"],"Recon plan")
        finally:sessions._sessions_dir=orig
class LocalMcpServerTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData();self.isolated.start()
        terminal.clear_ai_requests()
    def tearDown(self):
        mcp_local.stop_server();terminal.clear_ai_requests()
        self.isolated.stop()
    def test_server_runs_in_the_app_process_so_terminal_requests_reach_the_app(self):
        from mcp.client.client import Client
        st=mcp_local.start_server(18765)
        self.assertTrue(st["running"])
        self.assertTrue(ai.get_providers()["mcp"]["enabled"])
        ai.set_permissions_bulk(["terminal_read","terminal_run"],True)
        async def go():
            # The server needs its bearer token (S30); without it every request is a 401.
            import httpx2
            from mcp.client.streamable_http import streamable_http_client
            http=httpx2.AsyncClient(headers={"Authorization":"Bearer "+mcp_local.token_info(reveal=True)["token"]})
            async with Client(streamable_http_client(st["url"],http_client=http)) as c:
                await c.call_tool("terminal_run",{"command":"echo hi","reason":"test"})
        asyncio.run(go())
        self.assertEqual([r["command"] for r in terminal.list_ai_requests(True)],["echo hi"])
        mcp_local.stop_server()
        self.assertFalse(mcp_local.status()["running"])
        self.assertFalse(ai.get_providers()["mcp"]["enabled"])
if __name__=="__main__":unittest.main()
