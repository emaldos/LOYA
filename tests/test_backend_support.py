import os,socket,sqlite3,threading,time,unittest
from _isolate import IsolatedData,ROOT
from Cores import common_db
from Cores.Services import terminal_service as terminal
from Cores.Theme import tokens
class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.dir=self.isolated.start()
        self.path=os.path.join(self.dir,"migrate.db")
    def tearDown(self):
        self.isolated.stop()
    def test_upgrade_from_ten_adds_terminal_jobs(self):
        connection=sqlite3.connect(self.path)
        connection.execute("PRAGMA user_version=10")
        connection.commit()
        connection.close()
        connection=sqlite3.connect(self.path)
        common_db.ensure_schema(connection)
        version=connection.execute("PRAGMA user_version").fetchone()[0]
        table=connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='TerminalJobs'").fetchone()
        recorded=[row[0] for row in connection.execute("SELECT version FROM SchemaMigrations").fetchall()]
        connection.close()
        self.assertEqual(common_db.DB_SCHEMA_VERSION,version)
        self.assertIsNotNone(table)
        self.assertIn(11,recorded)
    def test_fresh_database_has_terminal_jobs(self):
        connection=sqlite3.connect(self.path)
        common_db.ensure_schema(connection)
        table=connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='TerminalJobs'").fetchone()
        connection.close()
        self.assertIsNotNone(table)
    def test_migration_is_idempotent(self):
        for _ in range(3):
            connection=sqlite3.connect(self.path)
            common_db.ensure_schema(connection)
            connection.close()
        connection=sqlite3.connect(self.path)
        count=connection.execute("SELECT COUNT(*) FROM SchemaMigrations WHERE version=11").fetchone()[0]
        connection.close()
        self.assertEqual(1,count)
class ElevationHandshakeTests(unittest.TestCase):
    def test_impostor_rejected_and_helper_accepted(self):
        server=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        server.bind(("127.0.0.1",0))
        server.listen(8)
        port=server.getsockname()[1]
        token=terminal.secrets.token_hex(terminal._ELEVATED_TOKEN_BYTES)
        def impostor():
            client=socket.socket()
            client.connect(("127.0.0.1",port))
            client.sendall(b"z"*(len(token)+1))
            time.sleep(0.2)
            client.close()
        def helper():
            time.sleep(0.3)
            client=socket.socket()
            client.connect(("127.0.0.1",port))
            client.sendall((token+"\n").encode("ascii"))
            time.sleep(1.5)
            client.close()
        threading.Thread(target=impostor,daemon=True).start()
        threading.Thread(target=helper,daemon=True).start()
        connection=terminal._accept_verified_connection(server,token,time.monotonic()+12)
        self.assertIsNotNone(connection)
        server.close()
    def test_timeout_raises_when_nobody_connects(self):
        server=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        server.bind(("127.0.0.1",0))
        server.listen(1)
        with self.assertRaises(RuntimeError):
            terminal._accept_verified_connection(server,"deadbeef",time.monotonic()+1)
        server.close()
    def test_helper_is_templated_in_memory(self):
        # SA-39: the helper is no longer written to disk; see test_security_audit.ElevatedHelperIsolationTests.
        token=terminal.secrets.token_hex(8)
        source=terminal.elevated_helper_source(token)
        self.assertIn(token,source)
        self.assertNotIn("__LOYA_ELEVATED_TOKEN__",source)
class ThemeTokenTests(unittest.TestCase):
    def test_every_theme_has_a_full_ansi_palette(self):
        for theme in ("dark","light","royal"):
            self.assertEqual(len(tokens.ANSI_NAMES),len(tokens.ANSI[theme]))
            rendered=tokens._ansi_rules(":root",theme)
            for name in tokens.ANSI_NAMES:
                self.assertIn("--ansi-%s:"%name,rendered)
                self.assertIn("--ansi-bg-%s:"%name,rendered)
    def test_background_variants_are_rgba(self):
        rendered=tokens._ansi_rules(":root","dark")
        self.assertIn("--ansi-bg-red:rgba(",rendered)
    def test_json_carries_ansi_tokens(self):
        payload=tokens.render_json()
        for theme in ("dark","light","royal"):
            self.assertEqual(len(tokens.ANSI_NAMES),len([key for key in payload[theme] if key.startswith("ansi-")]))
    def test_light_and_dark_reds_differ_for_contrast(self):
        payload=tokens.render_json()
        self.assertNotEqual(payload["light"]["ansi-red"],payload["dark"]["ansi-red"])
class DashboardWidgetTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
    def tearDown(self):
        self.isolated.stop()
    def test_counts_reflect_job_states(self):
        from Cores.Services import dashboard_service as dashboard
        self.assertEqual({"running":0,"failed":0,"total":0},dashboard._terminal_jobs())
        terminal.start_job("w1","s1","one");terminal.finish_job("w1",0)
        terminal.start_job("w2","s1","two");terminal.finish_job("w2",5)
        terminal.start_job("w3","s1","three")
        summary=dashboard._terminal_jobs()
        self.assertEqual(1,summary["running"])
        self.assertEqual(1,summary["failed"])
        self.assertEqual(3,summary["total"])
        value,detail=dashboard._stat_display("terminal_jobs",{"terminal_jobs":summary})
        self.assertEqual("1",value)
        self.assertIn("3",detail)
if __name__=="__main__":
    unittest.main()
