"""LOYA's local MCP server: bearer token, Host/Origin checks and the lock, tested with real HTTP requests."""
import json,os,socket,time,unittest,urllib.request,urllib.error
from _isolate import IsolatedData
from Cores import common_db
from Cores.Services import ai_service as ai
from Cores.Services import mcp_local_service as mcp
from Cores.Services import security_service as security
INIT={"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-06-18","capabilities":{},"clientInfo":{"name":"t","version":"1"}}}
def free_port():
    s=socket.socket();s.bind(("127.0.0.1",0));p=s.getsockname()[1];s.close();return p
class McpAuthTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.iso=IsolatedData();cls.iso.start()
        cls.port=free_port()
        mcp.start_server(cls.port,register_provider=False)
        cls.url=f"http://127.0.0.1:{cls.port}/mcp"
    @classmethod
    def tearDownClass(cls):
        mcp.stop_server()
        common_db.set_locked(False)
        cls.iso.stop()
    def tearDown(self):
        common_db.set_locked(False)
        ai.revoke_session_grant()
    def post(self,body,token=None,host=None,origin=None,session=None):
        req=urllib.request.Request(self.url,data=json.dumps(body).encode(),method="POST",headers={"Content-Type":"application/json","Accept":"application/json, text/event-stream"})
        if token is not None:req.add_header("Authorization","Bearer "+token)
        if host is not None:req.add_header("Host",host)
        if origin is not None:req.add_header("Origin",origin)
        if session:req.add_header("mcp-session-id",session)
        try:
            with urllib.request.urlopen(req,timeout=10) as r:return r.status,dict(r.headers),r.read().decode()
        except urllib.error.HTTPError as e:
            return e.code,dict(e.headers),e.read().decode()
    def token(self):return mcp.token_info(reveal=True)["token"]
    def test_no_token_is_401(self):
        code,headers,_=self.post(INIT)
        self.assertEqual(401,code)
        self.assertIn("Bearer",headers.get("www-authenticate",headers.get("WWW-Authenticate","")))
    def test_wrong_token_is_401(self):
        self.assertEqual(401,self.post(INIT,token="x"*43)[0])
        t=self.token()
        self.assertEqual(401,self.post(INIT,token=t[:-1]+("A" if t[-1]!="A" else "B"))[0])  # always a different last character
    def test_wrong_host_is_403(self):
        self.assertEqual(403,self.post(INIT,token=self.token(),host="evil.example:8765")[0])
        self.assertEqual(403,self.post(INIT,token=self.token(),host="127.0.0.1.evil.example")[0])
    def test_foreign_origin_is_403(self):
        self.assertEqual(403,self.post(INIT,token=self.token(),origin="http://evil.example")[0])
    def test_right_token_initializes(self):
        code,headers,body=self.post(INIT,token=self.token())
        self.assertEqual(200,code,body)
        self.assertIn("LOYA NG",body)
        self.assertEqual(200,self.post(INIT,token=self.token(),host=f"localhost:{self.port}",origin=f"http://localhost:{self.port}")[0])
    def test_locked_app_refuses_even_with_token(self):
        common_db.set_locked(True)
        self.assertEqual(423,self.post(INIT,token=self.token())[0])
    def test_token_is_masked_unless_revealed_and_reveal_is_audited(self):
        info=mcp.token_info()
        self.assertEqual("",info["token"])
        self.assertIn("…",info["masked"])
        self.assertNotIn(self.token()[4:-4],info["masked"])
        self.assertTrue(any(e["event"]=="mcp_token_copied" for e in security.list_audit_events(50)))
    def call_tool(self,token,name,args):
        code,headers,body=self.post(INIT,token=token)
        self.assertEqual(200,code,body)
        sid=headers.get("mcp-session-id") or headers.get("Mcp-Session-Id")
        self.post({"jsonrpc":"2.0","method":"notifications/initialized"},token=token,session=sid)
        code,_h,body=self.post({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":name,"arguments":args}},token=token,session=sid)
        self.assertEqual(200,code,body)
        return body
    def test_agent_token_identifies_the_agent_in_the_audit_log(self):
        tok=mcp.issue_client_token({"id":"run1","label":"Claude Agent","provider":"claude","session_id":"s42"})
        try:
            body=self.call_tool(tok,"notes_list",{})
            self.assertNotIn("isError\":true",body.replace(" ",""))
        finally:
            mcp.revoke_client_token(tok)
        rows=[e["detail"] for e in security.list_audit_events(50) if e["event"]=="ai_tool"]
        self.assertTrue(any(d.startswith("[Claude Agent session s42] notes_list - allowed") for d in rows),rows[:5])
        self.assertEqual(401,self.post(INIT,token=tok)[0])
    def test_client_header_cannot_be_spoofed(self):
        tok=self.token()
        req=urllib.request.Request(self.url,data=json.dumps(INIT).encode(),method="POST",headers={"Content-Type":"application/json","Accept":"application/json, text/event-stream","Authorization":"Bearer "+tok,"x-loya-client":json.dumps({"label":"LOYA AI"})})
        with urllib.request.urlopen(req,timeout=10) as r:self.assertEqual(200,r.status)
        self.assertIsNotNone(mcp.resolve_token(tok))
        self.assertEqual("external",mcp.resolve_token(tok)["id"])
    def test_denied_tool_is_refused_server_side(self):
        tok=mcp.issue_client_token({"id":"run2","label":"OpenAI Codex","provider":"codex","session_id":"s7"})
        try:body=self.call_tool(tok,"notes_delete",{"note_id":1})
        finally:mcp.revoke_client_token(tok)
        self.assertIn("Deny",body)
        rows=[e["detail"] for e in security.list_audit_events(50) if e["event"]=="ai_tool"]
        self.assertTrue(any("[OpenAI Codex session s7] notes_delete - denied by AI Roles" in d for d in rows))
class CheckRequestUnitTest(unittest.TestCase):
    def test_host_rules(self):
        for h in ("127.0.0.1:8765","localhost:1","[::1]:8765","LOCALHOST"):self.assertTrue(mcp._host_ok(h),h)
        for h in ("","evil:8765","127.0.0.1.nip.io","0.0.0.0:8765","10.0.0.5"):self.assertFalse(mcp._host_ok(h),h)
    def test_origin_rules(self):
        self.assertTrue(mcp._origin_ok(None))
        self.assertTrue(mcp._origin_ok("http://127.0.0.1:8765"))
        self.assertFalse(mcp._origin_ok("null"))
        self.assertFalse(mcp._origin_ok("https://attacker.example"))
    def test_order_host_before_token(self):
        self.assertEqual(403,mcp.check_request({"host":"evil"})[0])
        self.assertEqual(401,mcp.check_request({"host":"127.0.0.1"})[0])
if __name__=="__main__":
    unittest.main()
