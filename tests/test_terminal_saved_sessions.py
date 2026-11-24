import json,os,unittest
from _isolate import IsolatedData
from Cores.Services import terminal_service as terminal
class SavedSessionTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.dir=self.isolated.start()
    def tearDown(self):
        self.isolated.stop()
    def test_empty_store_has_sane_defaults(self):
        state=terminal.sessions_state()
        self.assertEqual([],state["saved"])
        self.assertEqual([],state["closed"])
        self.assertTrue(state["remember_output"])
        self.assertEqual("single",state["workspace"]["layout"])
    def test_saved_session_round_trips(self):
        state=terminal.save_saved_session({"name":"eng","shell_id":"shell","cwd":"~/eng","startup":"cd ~/eng\r\nsource venv/bin/activate"})
        entry=state["saved"][0]
        self.assertEqual("eng",entry["name"])
        self.assertEqual("~/eng",entry["cwd"])
        self.assertEqual("cd ~/eng\nsource venv/bin/activate",entry["startup"])
        self.assertTrue(entry["id"])
        self.assertTrue(os.path.isfile(os.path.join(self.dir,"terminal_sessions.json")))
    def test_saved_sessions_live_outside_settings_json(self):
        terminal.save_saved_session({"name":"eng","scrollback":"x"*100})
        settings=os.path.join(self.dir,"settings.json")
        if os.path.isfile(settings):
            with open(settings,encoding="utf-8") as f:self.assertNotIn("eng",f.read())
    def test_a_name_is_required(self):
        with self.assertRaises(ValueError):terminal.save_saved_session({"name":"   "})
        with self.assertRaises(ValueError):terminal.save_saved_session("junk")
    def test_fields_are_capped(self):
        entry=terminal.save_saved_session({"name":"n"*200,"cwd":"c"*5000,"startup":"s"*9000,"shell_id":"x"*500,"scrollback":"line\n"*40000})["saved"][0]
        self.assertEqual(60,len(entry["name"]))
        self.assertEqual(1024,len(entry["cwd"]))
        self.assertEqual(terminal.SAVED_STARTUP_MAX,len(entry["startup"]))
        self.assertEqual(64,len(entry["shell_id"]))
        self.assertLessEqual(len(entry["scrollback"]),terminal.SAVED_SCROLLBACK_MAX)
    def test_editing_keeps_saved_output_unless_cleared(self):
        entry=terminal.save_saved_session({"name":"a","scrollback":"old output\n"})["saved"][0]
        edited=terminal.save_saved_session({"id":entry["id"],"name":"b"})["saved"]
        self.assertEqual(1,len(edited))
        self.assertEqual("b",edited[0]["name"])
        self.assertEqual("old output\n",edited[0]["scrollback"])
        self.assertEqual(entry["created"],edited[0]["created"])
        cleared=terminal.save_saved_session({"id":entry["id"],"name":"b","scrollback":""})["saved"][0]
        self.assertEqual("",cleared["scrollback"])
    def test_delete(self):
        a=terminal.save_saved_session({"name":"a"})["saved"][0]
        terminal.save_saved_session({"name":"b"})
        names=[x["name"] for x in terminal.delete_saved_session(a["id"])["saved"]]
        self.assertEqual(["b"],names)
    def test_saved_list_is_bounded(self):
        for i in range(terminal.SAVED_SESSIONS_MAX):terminal.save_saved_session({"name":f"s{i}"})
        with self.assertRaises(ValueError):terminal.save_saved_session({"name":"one too many"})
    def test_ids_are_sanitised(self):
        entry=terminal.save_saved_session({"id":"../../etc<script>","name":"x"})["saved"][0]
        self.assertRegex(entry["id"],r"^[0-9a-zA-Z_-]+$")
    def test_corrupt_store_is_treated_as_empty(self):
        with open(os.path.join(self.dir,"terminal_sessions.json"),"w",encoding="utf-8") as f:f.write("{not json")
        self.assertEqual([],terminal.sessions_state()["saved"])
        terminal.save_saved_session({"name":"recovered"})
        self.assertEqual("recovered",terminal.sessions_state()["saved"][0]["name"])
    def test_garbage_entries_in_the_file_are_dropped(self):
        with open(os.path.join(self.dir,"terminal_sessions.json"),"w",encoding="utf-8") as f:json.dump({"saved":[1,None,{"name":""},{"name":"ok"}],"closed":"nope","workspace":[]},f)
        state=terminal.sessions_state()
        self.assertEqual(["ok"],[x["name"] for x in state["saved"]])
        self.assertEqual([],state["closed"])
        self.assertEqual("single",state["workspace"]["layout"])
class ClosedSessionTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.dir=self.isolated.start()
    def tearDown(self):
        self.isolated.stop()
    def test_newest_first_and_trimmed_to_ten(self):
        for i in range(14):terminal.remember_closed_session(None,{"name":f"s{i}","cwd":"/tmp"})
        closed=terminal.sessions_state()["closed"]
        self.assertEqual(terminal.CLOSED_SESSIONS_MAX,len(closed))
        self.assertEqual("s13",closed[0]["name"])
        self.assertEqual("s4",closed[-1]["name"])
    def test_scrollback_is_plain_redacted_and_bounded(self):
        noisy="\x1b[31mred\x1b[0m\r\n10%\r100%\npassword=hunter2\n"+("y"*100+"\n")*1000
        entry=terminal.remember_closed_session(None,{"name":"a","scrollback":noisy})["closed"][0]
        self.assertNotIn("\x1b",entry["scrollback"])
        self.assertNotIn("hunter2",entry["scrollback"])
        self.assertLessEqual(len(entry["scrollback"]),terminal.CLOSED_SCROLLBACK_MAX)
        self.assertTrue(entry["scrollback"].endswith("y\n"))
        short=terminal.remember_closed_session(None,{"name":"b","scrollback":"\x1b[31mred\x1b[0m\r\n10%\r100%\n"})["closed"][0]
        self.assertEqual("red\n100%\n",short["scrollback"])
    def test_pop_takes_the_newest_and_removes_it(self):
        terminal.remember_closed_session(None,{"name":"old"})
        terminal.remember_closed_session(None,{"name":"new"})
        state=terminal.pop_closed_session()
        self.assertEqual("new",state["entry"]["name"])
        self.assertEqual(["old"],[x["name"] for x in state["closed"]])
    def test_pop_by_id(self):
        terminal.remember_closed_session(None,{"name":"a"})
        b=terminal.remember_closed_session(None,{"name":"b"})["closed"][0]
        terminal.remember_closed_session(None,{"name":"c"})
        state=terminal.pop_closed_session(b["id"])
        self.assertEqual("b",state["entry"]["name"])
        self.assertEqual(["c","a"],[x["name"] for x in state["closed"]])
    def test_pop_on_an_empty_list_returns_nothing(self):
        self.assertIsNone(terminal.pop_closed_session()["entry"])
        self.assertIsNone(terminal.pop_closed_session("missing")["entry"])
    def test_forget_one_or_all(self):
        terminal.remember_closed_session(None,{"name":"a"})
        b=terminal.remember_closed_session(None,{"name":"b"})["closed"][0]
        self.assertEqual(["a"],[x["name"] for x in terminal.forget_closed_session(b["id"])["closed"]])
        self.assertEqual([],terminal.forget_closed_session(None)["closed"])
    def test_turning_off_remember_output_drops_stored_output(self):
        terminal.remember_closed_session(None,{"name":"a","scrollback":"secret-ish output"})
        state=terminal.set_remember_output(False)
        self.assertFalse(state["remember_output"])
        self.assertEqual("",state["closed"][0]["scrollback"])
        entry=terminal.remember_closed_session(None,{"name":"b","scrollback":"more"})["closed"][0]
        self.assertEqual("",entry["scrollback"])
        with open(os.path.join(self.dir,"terminal_sessions.json"),encoding="utf-8") as f:raw=json.load(f)
        self.assertTrue(all(not x.get("scrollback") for x in raw["closed"]))
    def test_a_nameless_session_gets_a_name(self):
        self.assertEqual("Terminal",terminal.remember_closed_session(None,{})["closed"][0]["name"])
class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
    def tearDown(self):
        self.isolated.stop()
    def test_round_trip(self):
        terminal.set_workspace({"layout":"top1bottom2","ratios":{"v":0.3,"h":0.6},"focus":2,"panes":[{"name":"recon","shell_id":"shell","cwd":"/tmp"},None,{"name":"logs"}]})
        ws=terminal.sessions_state()["workspace"]
        self.assertEqual("top1bottom2",ws["layout"])
        self.assertEqual({"v":0.3,"h":0.6},ws["ratios"])
        self.assertEqual(2,ws["focus"])
        self.assertEqual("recon",ws["panes"][0]["name"])
        self.assertIsNone(ws["panes"][1])
    def test_validation(self):
        ws=terminal.clean_workspace({"layout":"hexagon","ratios":{"v":"x","h":7},"focus":99,"panes":[{}]*9})
        self.assertEqual("single",ws["layout"])
        self.assertEqual({"v":0.5,"h":0.9},ws["ratios"])
        self.assertEqual(0,ws["focus"])
        self.assertEqual(1,len(ws["panes"]))
        self.assertEqual(4,len(terminal.clean_workspace({"layout":"grid4","panes":[{}]*9})["panes"]))
        self.assertEqual(0.5,terminal.clean_workspace({"ratios":{"v":float("nan")}})["ratios"]["v"])
    def test_workspace_writes_keep_saved_sessions(self):
        terminal.save_saved_session({"name":"keep me"})
        terminal.set_workspace({"layout":"cols2"})
        terminal.remember_closed_session(None,{"name":"closed"})
        state=terminal.sessions_state()
        self.assertEqual(["keep me"],[x["name"] for x in state["saved"]])
        self.assertEqual("cols2",state["workspace"]["layout"])
        self.assertEqual(1,len(state["closed"]))
class StartupAndCwdTests(unittest.TestCase):
    def test_startup_lines_get_the_shell_newline_and_blank_lines_drop(self):
        text=terminal._startup_payload("shell","cd ~/eng\r\n\r\n  \nsource venv/bin/activate")
        nl="\r\n" if terminal._IS_WINDOWS else "\n"
        self.assertEqual("cd ~/eng"+nl+"source venv/bin/activate"+nl,text)
        self.assertEqual("",terminal._startup_payload("shell","  \n "))
    def test_wsl_startup_uses_lf(self):
        self.assertTrue(terminal._startup_payload("wsl:Ubuntu","ls").endswith("ls\n"))
    def test_cwd_expands_home_and_rejects_missing_folders(self):
        self.assertEqual(os.path.expanduser("~"),terminal._expand_cwd("~"))
        self.assertEqual("",terminal._expand_cwd("/definitely/not/here/loya"))
        self.assertEqual("",terminal._expand_cwd(""))
    def test_unknown_sessions_are_harmless(self):
        self.assertEqual("",terminal.session_cwd("nope"))
        self.assertFalse(terminal.set_session_label("nope","x"))
        self.assertEqual({"out":{},"alive":{"nope":False}},terminal.poll_sessions(["nope"],["nope"]))
    def test_shortcut_defaults_cover_the_new_actions(self):
        for action,combo in (("reopen_closed","Ctrl+Shift+T"),("pane_left","Alt+ArrowLeft"),("pane_down","Alt+ArrowDown")):
            self.assertEqual(combo,terminal.SHORTCUT_DEFAULTS[action])
            self.assertEqual("",terminal.shortcut_conflict(combo))
        self.assertTrue(terminal.shortcut_conflict("Ctrl+Alt+ArrowLeft"))
@unittest.skipIf(terminal._IS_WINDOWS,"posix pty")
class LiveSessionTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
        self.sid=None
    def tearDown(self):
        if self.sid:terminal.close_session(self.sid)
        self.isolated.stop()
    def _wait_for(self,needle,timeout=6):
        import time
        seen="";deadline=time.time()+timeout
        while time.time()<deadline:
            res=terminal.poll_sessions([self.sid],[self.sid])
            seen+=res["out"].get(self.sid,"")
            if needle in seen:return seen
            time.sleep(0.1)
        return seen
    def test_cwd_startup_label_and_live_cwd(self):
        import tempfile
        folder=os.path.realpath(tempfile.mkdtemp(prefix="loya_cwd_"))
        try:
            self.sid=terminal.create_session("shell",None,100,30,folder,"echo LOYA_STARTUP_$((40+2))","named")
            self.assertEqual("named",terminal._sessions[self.sid].label)
            self.assertIn("LOYA_STARTUP_42",self._wait_for("LOYA_STARTUP_42"))
            self.assertEqual(folder,terminal.session_cwd(self.sid))
            self.assertTrue(terminal.set_session_label(self.sid,"renamed"))
            self.assertEqual("renamed",terminal._sessions[self.sid].label)
            state=terminal.remember_closed_session(self.sid,{"name":"renamed","cwd":"/stale"})
            self.assertEqual(folder,state["closed"][0]["cwd"])
        finally:
            os.rmdir(folder) if os.path.isdir(folder) and not os.listdir(folder) else None
if __name__=="__main__":unittest.main()
