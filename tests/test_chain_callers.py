import sqlite3,time,unittest
from _isolate import IsolatedData
from Cores import common_db,chain_callers
from Cores.Services import playbooks_service as playbooks
from Cores.Services import terminal_service as terminal
class CallerRulesTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual("recon",chain_callers.normalize_caller("  /Recon "))
    def test_errors(self):
        self.assertEqual("",chain_callers.caller_error("web-quick_1"))
        self.assertIn("required",chain_callers.caller_error(""))
        self.assertIn("at most",chain_callers.caller_error("a"*33))
        self.assertIn("only use",chain_callers.caller_error("a b"))
        self.assertIn("only use",chain_callers.caller_error("a/b"))
        self.assertEqual("",chain_callers.caller_error("chain"))   # /chain is a user caller again: the AI command is /newchain
        self.assertEqual("chain",chain_callers.normalize_caller("/Chain"))
        for name in ("help","explain","summarize-note","new-note","new-command","fix-command","suggest-next","run","target","search","newchain"):
            self.assertIn("built-in",chain_callers.caller_error(name))
    def test_slugify_and_suggest(self):
        self.assertEqual("demo-external-web-quick-wins",chain_callers.slugify_caller("DEMO External web quick wins!"))
        self.assertEqual("enum-smb-ldap",chain_callers.slugify_caller("  Énum SMB / LDAP "))
        self.assertEqual(32,len(chain_callers.slugify_caller("x"*60)))
        self.assertEqual("recon-2",chain_callers.suggest_caller("Recon",{"recon"}))
        self.assertEqual("help-chain",chain_callers.suggest_caller("Help"))
        self.assertEqual("chain",chain_callers.suggest_caller("!!!"))
        long=chain_callers.suggest_caller("y"*40,{"y"*32})
        self.assertTrue(long.endswith("-2") and len(long)<=32)
class CallerServiceTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
    def tearDown(self):
        self.isolated.stop()
    def test_create_suggests_a_unique_caller(self):
        a=playbooks.create_playbook("Recon")
        b=playbooks.create_playbook("Recon")
        callers={pb["id"]:pb["caller"] for pb in playbooks.list_playbooks()}
        self.assertEqual("recon",callers[a])
        self.assertEqual("recon-2",callers[b])
    def test_create_with_explicit_and_empty_caller(self):
        a=playbooks.create_playbook("Web",caller="/WebScan")
        b=playbooks.create_playbook("No caller",caller="")
        self.assertEqual("webscan",playbooks.get_playbook(a)["caller"])
        self.assertEqual("",playbooks.get_playbook(b)["caller"])
        self.assertEqual(["webscan"],[c["caller"] for c in playbooks.list_callers()])
    def test_uniqueness_and_reserved(self):
        a=playbooks.create_playbook("One",caller="one")
        b=playbooks.create_playbook("Two",caller="two")
        with self.assertRaises(ValueError):playbooks.create_playbook("Again",caller="one")
        with self.assertRaises(ValueError):playbooks.set_caller(b,"one")
        with self.assertRaises(ValueError):playbooks.set_caller(b,"help")
        with self.assertRaises(ValueError):playbooks.set_caller(b,"bad caller")
        self.assertEqual("one",playbooks.set_caller(a,"one"))
        self.assertEqual("",playbooks.set_caller(b,""))
        self.assertEqual("One",playbooks.find_by_caller("/one")["name"])
        self.assertFalse(playbooks.validate_caller("one",b)["ok"])
        self.assertTrue(playbooks.validate_caller("one",a)["ok"])
    def test_migration_adds_columns_and_backfills_callers(self):
        # A v13 database: Playbooks without caller, TerminalJobs without skip_reason/chain_name.
        con=sqlite3.connect(common_db.db_path())
        con.execute("CREATE TABLE Playbooks(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,created_at TEXT,updated_at TEXT)")
        con.execute("CREATE TABLE TerminalJobs(id INTEGER PRIMARY KEY AUTOINCREMENT,job_key TEXT NOT NULL UNIQUE,session_id TEXT,label TEXT,command TEXT,source TEXT,state TEXT NOT NULL,exit_code INTEGER,started_at TEXT NOT NULL,ended_at TEXT,cwd TEXT,bytes_out INTEGER DEFAULT 0,chain_id TEXT,chain_pos INTEGER)")
        con.executemany("INSERT INTO Playbooks(name) VALUES(?)",[("Web Recon",),("Web Recon",),("Help",)])
        con.execute("INSERT INTO TerminalJobs(job_key,state,started_at) VALUES('old','done','2026-01-01')")
        con.execute("PRAGMA user_version=13")
        con.commit()
        con.close()
        con=sqlite3.connect(common_db.db_path())
        common_db.ensure_schema(con)
        self.assertEqual(common_db.DB_SCHEMA_VERSION,con.execute("PRAGMA user_version").fetchone()[0])
        self.assertGreaterEqual(common_db.DB_SCHEMA_VERSION,14)
        names=[r[0] for r in con.execute("SELECT caller FROM Playbooks ORDER BY id")]
        self.assertEqual(["web-recon","web-recon-2","help-chain"],names)
        cols={r[1] for r in con.execute("PRAGMA table_info(TerminalJobs)")}
        self.assertTrue({"skip_reason","chain_name"}<=cols)
        self.assertEqual(1,con.execute("SELECT COUNT(*) FROM TerminalJobs WHERE job_key='old'").fetchone()[0])
        # Running the migrations again changes nothing.
        common_db.ensure_schema(con)
        self.assertEqual(names,[r[0] for r in con.execute("SELECT caller FROM Playbooks ORDER BY id")])
        con.close()
class ChainStopTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
        self.shell=terminal.list_shells()[0]["id"]
    def tearDown(self):
        terminal.clear_batch_output()
        self.isolated.stop()
    def wait(self,chain_id):
        deadline=time.time()+30
        while time.time()<deadline:
            status=terminal.chain_status(chain_id)
            if status and not status["active"]:return status
            time.sleep(0.05)
        return terminal.chain_status(chain_id)
    def test_stops_before_the_first_step_with_a_skip_reason(self):
        items=[{"command":"echo one"},{"command":"echo two"},{"command":"echo {Username}","skip_reason":"Missing {Username}"},{"command":"echo four"}]
        started=terminal.start_chain(self.shell,items,"continue","playbook","DEMO chain")
        self.assertEqual(2,started["stop_at"])
        status=self.wait(started["chain_id"])
        self.assertEqual(["done","done","skipped","skipped"],[s["state"] for s in status["steps"]])
        self.assertEqual("Missing {Username}",status["steps"][2]["skip_reason"])
        self.assertEqual("Chain stopped before step 3",status["steps"][3]["skip_reason"])
        self.assertEqual("DEMO chain",status["chain_name"])
    def test_failure_reason_on_later_steps(self):
        started=terminal.start_chain(self.shell,[{"command":"echo one"},{"command":"exit 3"},{"command":"echo three"}],"stop")
        status=self.wait(started["chain_id"])
        self.assertEqual(["done","failed","skipped"],[s["state"] for s in status["steps"]])
        self.assertEqual("Step 2 failed",status["steps"][2]["skip_reason"])
        self.assertIsNone(status["steps"][0]["skip_reason"])
if __name__=="__main__":
    unittest.main()
