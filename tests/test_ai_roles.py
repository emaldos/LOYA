"""AI Roles: the permission engine every AI tool call (in-app chat, external MCP clients, external agents) goes through."""
import threading,time,unittest
from _isolate import IsolatedData
from Cores import common_db
from Cores.Services import ai_service as ai
from Cores.Services import ai_chat_service as chat
from Cores.Services import security_service as security
class Base(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.iso.start()
        ai.revoke_session_grant()
    def tearDown(self):
        ai.revoke_session_grant()
        common_db.set_locked(False)
        self.iso.stop()
    def audit(self):return [e["detail"] for e in security.list_audit_events(200) if e["event"]=="ai_tool"]
class RegistryTest(Base):
    def test_every_mcp_tool_is_covered_exactly_once(self):
        names=[t.name for t in chat._list_tools()]
        self.assertTrue(names)
        for n in names:
            keys=[k for k,tools in ai.PERMISSION_TOOL_MAP.items() if n in tools]
            self.assertEqual(1,len(keys),f"{n} covered by {keys}")
        listed={t for tools in ai.PERMISSION_TOOL_MAP.values() for t in tools}
        self.assertEqual(set(),listed-set(names),"permissions name tools the MCP server does not have")
    def test_entities_include_the_extended_set(self):
        ents={e for e,_a in ai.PERMISSION_LABELS.values()}
        for e in ("Notes","Commands","Targets","Quick Run","Action Chains","Tags","Recycle Bin","Settings","Terminal","Reports"):self.assertIn(e,ents)
    def test_defaults_deletes_and_shell_off(self):
        lv=ai.get_permission_levels()
        for k in ai.PERMISSION_TOOL_MAP:
            if k in ai._DELETE_PERMISSION_KEYS or k in ai._SHELL_PERMISSION_KEYS:self.assertEqual("deny",lv[k],k)
        self.assertEqual("deny",lv["terminal_read"]);self.assertEqual("deny",lv["terminal_run"]);self.assertEqual("deny",lv["terminal_kill"])
    def test_register_permission_is_easy_to_extend(self):
        try:
            ai.register_permission("widgets_read","Widgets","Read",["widgets_list"])
            ai.register_permission("widgets_delete","Widgets","Delete",["widgets_delete"])
            self.assertEqual("allow",ai.get_permission_levels()["widgets_read"])
            self.assertEqual("deny",ai.get_permission_levels()["widgets_delete"])
            self.assertEqual("widgets_read",ai.permission_key("widgets_list"))
        finally:
            for k in ("widgets_read","widgets_delete"):
                ai.PERMISSION_TOOL_MAP.pop(k,None);ai.PERMISSION_LABELS.pop(k,None);ai._DEFAULT_LEVELS.pop(k,None);ai._DELETE_PERMISSION_KEYS.discard(k)
            ai._ENTITY_ACTIONS.pop("Widgets",None)
class LevelsTest(Base):
    def test_presets(self):
        ro=ai.preset_levels("read_only")
        self.assertEqual("allow",ro["notes_read"]);self.assertEqual("deny",ro["notes_add"]);self.assertEqual("deny",ro["terminal_read"])
        asst=ai.preset_levels("assistant")
        self.assertEqual(("allow","ask","ask","deny"),(asst["notes_read"],asst["notes_add"],asst["notes_edit"],asst["notes_delete"]))
        self.assertEqual("ask",asst["terminal_read"]);self.assertEqual("deny",asst["terminal_run"])
        full=ai.preset_levels("full")
        self.assertEqual(("allow","allow","ask","ask"),(full["notes_add"],full["notes_edit"],full["notes_delete"],full["terminal_run"]))
        ai.apply_preset("assistant");self.assertEqual("assistant",ai.current_preset())
        ai.set_permission_levels({"notes_add":"allow"});self.assertEqual("custom",ai.current_preset())
        with self.assertRaises(ValueError):ai.preset_levels("root")
    def test_nothing_is_more_open_than_read(self):
        ai.set_permission_levels({"notes_read":"ask","notes_add":"allow"})
        self.assertEqual("ask",ai.get_permission_levels()["notes_add"])
        ai.set_permission_levels({"notes_read":"deny"})
        lv=ai.get_permission_levels()
        self.assertEqual(("deny","deny","deny"),(lv["notes_add"],lv["notes_edit"],lv["notes_delete"]))
    def test_bad_values_rejected(self):
        with self.assertRaises(ValueError):ai.set_permission_levels({"nope":"allow"})
        with self.assertRaises(ValueError):ai.set_permission_levels({"notes_add":"sometimes"})
class AuthorizeTest(Base):
    def test_unknown_tool_blocked_and_logged(self):
        with self.assertRaises(ai.AIPermissionError):ai.authorize("rm_rf",{})
        self.assertTrue(any("rm_rf - blocked" in d for d in self.audit()))
    def test_deny_raises_server_side_through_the_tool(self):
        ok,msg=chat._call_tool("notes_delete",{"note_id":1})
        self.assertFalse(ok);self.assertIn("Deny",msg)
        self.assertTrue(any("notes_delete - denied by AI Roles" in d for d in self.audit()))
    def answer(self,decision,delay=0.2):
        def run():
            end=time.time()+5
            while time.time()<end:
                rows=ai.pending_approvals()
                if rows:
                    self.seen=rows[0];ai.resolve_approval(rows[0]["id"],decision);return
                time.sleep(0.02)
        t=threading.Thread(target=run,daemon=True);t.start();return t
    def test_ask_allow_once(self):
        ai.set_permission_levels({"notes_add":"ask"})
        t=self.answer("once")
        self.assertEqual("allow",ai.authorize("notes_create",{"name":"x","content":"y"}))
        t.join()
        self.assertEqual("ask",ai.tool_decision("notes_create"))
        self.assertTrue(any("notes_create - approved once" in d for d in self.audit()))
    def test_ask_deny(self):
        ai.set_permission_levels({"notes_add":"ask"})
        t=self.answer("deny")
        with self.assertRaises(ai.AIPermissionError):ai.authorize("notes_create",{"name":"x"})
        t.join()
        self.assertTrue(any("declined by the operator" in d for d in self.audit()))
    def test_session_grant(self):
        ai.set_permission_levels({"notes_add":"ask"})
        t=self.answer("session")
        ai.authorize("notes_create",{"name":"x"});t.join()
        self.assertEqual("allow",ai.tool_decision("notes_create"))
        self.assertEqual(["notes_add"],[g["key"] for g in ai.session_grants()])
        ai.revoke_session_grant("notes_add")
        self.assertEqual("ask",ai.tool_decision("notes_create"))
    def test_timeout_expires(self):
        ai.set_permission_levels({"notes_add":"ask"})
        self.assertEqual("expired",ai.request_approval("notes_create","",timeout=0.05))
    def test_terminal_run_goes_to_terminal_queue(self):
        ai.set_permission_levels({"terminal_read":"allow","terminal_run":"ask"})
        self.assertEqual("ask",ai.authorize("terminal_run",{"command":"id"},defer_ask=True))
    def test_approval_shows_client_and_reason(self):
        ai.set_permission_levels({"notes_add":"ask"})
        hook=lambda c:"I need to save the scan summary as a note." if c and c.get("id")=="r1" else ""
        ai.register_reason_hook(hook)
        try:
            tok=ai.set_client({"id":"r1","label":"Claude Agent","provider":"claude","session_id":"s1"})
            try:
                t=self.answer("once")
                ai.authorize("notes_create",{"name":"x","content":"password: hunter2"})
                t.join()
            finally:ai.reset_client(tok)
        finally:ai._client_reason_hooks.remove(hook)
        self.assertEqual("Claude Agent",self.seen["client"])
        self.assertIn("save the scan summary",self.seen["reason"])
        self.assertNotIn("hunter2",self.seen["summary"])
        self.assertTrue(any(d.startswith("[Claude Agent session s1] notes_create - approved once") for d in self.audit()))
    def test_cancel_client_approvals(self):
        ai.set_permission_levels({"notes_add":"ask"})
        out={}
        def ask():
            tok=ai.set_client({"id":"runZ","label":"OpenAI Codex"})
            try:out["r"]=ai.request_approval("notes_create","",timeout=10)
            finally:ai.reset_client(tok)
        t=threading.Thread(target=ask);t.start()
        end=time.time()+5
        while not ai.pending_approvals() and time.time()<end:time.sleep(0.02)
        self.assertEqual(0,ai.cancel_client_approvals("other"))
        self.assertEqual(1,ai.cancel_client_approvals("runZ"))
        t.join(5)
        self.assertEqual("denied",out["r"])
        self.assertEqual([],ai.pending_approvals())
    def test_activity_log(self):
        chat._call_tool("notes_list",{})
        self.assertTrue(any("notes_list - allowed" in a["detail"] for a in ai.activity(10)))
if __name__=="__main__":
    unittest.main()
