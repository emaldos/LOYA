"""Chain Diagrams storage: the v16 migration, ChainGraphs rows and the ChainRuns history."""
import os,sys,sqlite3,unittest
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from Cores import common_db
from Cores.Services import flow_store as store
from Cores.Services import playbooks_service as chains
GRAPH={"schema":1,"settings":{},"nodes":[{"id":"n1","type":"start","title":"Start","x":0,"y":0,"config":{}},{"id":"n2","type":"end","title":"End","x":200,"y":0,"config":{}}],"edges":[{"id":"e1","from":"n1","port":"out","to":"n2"}]}
def run_status(run_id,playbook_id=1,state="done",mode="run",**extra):
    base={"run_id":run_id,"playbook_id":playbook_id,"name":"demo","mode":mode,"state":state,"reason":"","source":"manual","target":"box","started_at":"2026-01-01T00:00:00+00:00","ended_at":"2026-01-01T00:00:05+00:00","nodes":{"n1":{"state":"success","output":{"stdout":"hi","stderr":""}}},"edges_taken":["e1"],"events":[{"seq":1,"ts":"t","node":None,"level":"info","text":"Run started"}],"vars":{"a":1},"seq":1}
    base.update(extra)
    return base
class Base(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.iso.start()
    def tearDown(self):
        common_db.set_locked(False)
        self.iso.stop()
class MigrationTest(Base):
    def old_db(self,version=15):
        con=sqlite3.connect(common_db.db_path())
        try:
            con.execute("CREATE TABLE Playbooks(id INTEGER PRIMARY KEY AUTOINCREMENT,name TEXT NOT NULL,created_at TEXT,updated_at TEXT,caller TEXT)")
            con.execute("CREATE TABLE PlaybookSteps(id INTEGER PRIMARY KEY AUTOINCREMENT,playbook_id INTEGER NOT NULL,command_id INTEGER NOT NULL,command_src TEXT NOT NULL,position INTEGER NOT NULL)")
            con.execute("INSERT INTO Playbooks(name,caller) VALUES('Old chain','old')")
            con.execute("INSERT INTO PlaybookSteps(playbook_id,command_id,command_src,position) VALUES(1,7,'Commands',0)")
            con.execute("PRAGMA user_version=%d"%version)
            con.commit()
        finally:
            con.close()
    def tables(self,con):
        return {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type IN ('table','index')")}
    def test_schema_version_is_16_or_later(self):
        self.assertGreaterEqual(common_db.DB_SCHEMA_VERSION,16)
    def test_a_v15_database_gains_the_tables_and_keeps_its_chains(self):
        self.old_db(15)
        con=sqlite3.connect(common_db.db_path())
        try:
            common_db.ensure_schema(con)
            names=self.tables(con)
            for name in ("ChainGraphs","ChainRuns","ChainRunLogs","idx_chain_runs_playbook","idx_chain_runs_started","idx_chain_run_logs_run"):self.assertIn(name,names)
            self.assertEqual(common_db.DB_SCHEMA_VERSION,con.execute("PRAGMA user_version").fetchone()[0])
            self.assertEqual([(1,"Old chain","old")],con.execute("SELECT id,name,caller FROM Playbooks").fetchall())
            self.assertEqual([(1,7,"Commands",0)],con.execute("SELECT playbook_id,command_id,command_src,position FROM PlaybookSteps").fetchall())
            self.assertEqual(1,con.execute("SELECT COUNT(*) FROM SchemaMigrations WHERE version=16").fetchone()[0])
            self.assertEqual(0,con.execute("SELECT COUNT(*) FROM ChainGraphs").fetchone()[0])
        finally:
            con.close()
    def test_migration_is_idempotent(self):
        self.old_db(15)
        for _ in range(2):
            con=sqlite3.connect(common_db.db_path())
            try:common_db.ensure_schema(con)
            finally:con.close()
        self.assertFalse(store.has_graph(1))
    def test_a_database_that_claims_v16_without_the_tables_heals(self):
        self.old_db(16)
        self.assertEqual({},store.graph_index())
    def test_a_fresh_database_has_the_tables(self):
        con=sqlite3.connect(common_db.db_path())
        try:
            common_db.ensure_schema(con)
            self.assertIn("ChainGraphs",self.tables(con))
            columns=[r[1] for r in con.execute("PRAGMA table_info(ChainGraphs)")]
            self.assertEqual(["playbook_id","graph","schema_version","ai_made","ai_reviewed","ai_client","created_at","updated_at"],columns)
            columns=[r[1] for r in con.execute("PRAGMA table_info(ChainRuns)")]
            self.assertEqual(["id","run_id","playbook_id","chain_name","mode","state","source","target","started_at","ended_at","data"],columns)
        finally:
            con.close()
class GraphRowsTest(Base):
    def setUp(self):
        super().setUp()
        self.pid=chains.create_playbook("Demo")
    def test_no_row_means_linear(self):
        self.assertIsNone(store.get_graph_row(self.pid))
        self.assertFalse(store.has_graph(self.pid))
    def test_save_and_read_back(self):
        out=store.save_graph(self.pid,GRAPH)
        self.assertTrue(out["created"])
        row=store.get_graph_row(self.pid)
        self.assertEqual(GRAPH,row["graph"])
        self.assertEqual((False,True,""),(row["ai_made"],row["ai_reviewed"],row["ai_client"]))
        self.assertTrue(row["created_at"]);self.assertTrue(row["updated_at"])
    def test_ai_flags_survive_a_plain_save(self):
        store.save_graph(self.pid,GRAPH,ai_made=True,ai_reviewed=False,ai_client="Claude")
        created=store.get_graph_row(self.pid)["created_at"]
        out=store.save_graph(self.pid,dict(GRAPH,settings={"on_error":"continue"}))
        self.assertFalse(out["created"])
        row=store.get_graph_row(self.pid)
        self.assertEqual((True,False,"Claude"),(row["ai_made"],row["ai_reviewed"],row["ai_client"]))
        self.assertEqual(created,row["created_at"])
        self.assertEqual("continue",row["graph"]["settings"]["on_error"])
    def test_set_reviewed(self):
        store.save_graph(self.pid,GRAPH,ai_made=True,ai_reviewed=False,ai_client="x")
        self.assertTrue(store.set_reviewed(self.pid))
        self.assertTrue(store.get_graph_row(self.pid)["ai_reviewed"])
        self.assertFalse(store.set_reviewed(9999))
    def test_graph_index_counts_nodes(self):
        store.save_graph(self.pid,GRAPH,ai_made=True,ai_reviewed=False)
        self.assertEqual({self.pid:{"node_count":2,"ai_made":True,"ai_reviewed":False}},{k:{x:v[x] for x in ("node_count","ai_made","ai_reviewed")} for k,v in store.graph_index().items()})
    def test_delete_graph_leaves_the_chain(self):
        store.save_graph(self.pid,GRAPH)
        self.assertTrue(store.delete_graph(self.pid))
        self.assertFalse(store.delete_graph(self.pid))
        self.assertIsNotNone(chains.get_playbook(self.pid))
    def test_unknown_chain_is_refused(self):
        with self.assertRaises(ValueError):store.save_graph(4242,GRAPH)
        with self.assertRaises(ValueError):store.save_graph(self.pid,"not a graph")
        with self.assertRaises(ValueError):store.get_graph_row("abc")
    def test_locked_database_raises(self):
        common_db.set_locked(True)
        with self.assertRaises(common_db.DatabaseLocked):store.get_graph_row(self.pid)
        with self.assertRaises(common_db.DatabaseLocked):store.save_run(run_status("r1"))
class RunRowsTest(Base):
    def test_save_list_get_delete(self):
        store.save_run(run_status("r1",1))
        store.save_run(run_status("r2",2,state="failed",mode="dry"))
        rows=store.list_runs()
        self.assertEqual(["r2","r1"],[r["run_id"] for r in rows])
        self.assertEqual({"run_id":"r2","playbook_id":2,"chain_name":"demo","mode":"dry","state":"failed","source":"manual","target":"box","started_at":"2026-01-01T00:00:00+00:00","ended_at":"2026-01-01T00:00:05+00:00"},rows[0])
        self.assertEqual(["r1"],[r["run_id"] for r in store.list_runs(1)])
        self.assertEqual({"a":1},store.get_run("r1")["vars"])
        self.assertIsNone(store.get_run("nope"))
        self.assertTrue(store.delete_run("r1"));self.assertFalse(store.delete_run("r1"))
        self.assertEqual(1,store.clear_runs(2));self.assertEqual([],store.list_runs())
    def test_saving_the_same_run_again_updates_it(self):
        store.save_run(run_status("r1",state="running",ended_at=""))
        store.save_run(run_status("r1",state="done"))
        self.assertEqual(["done"],[r["state"] for r in store.list_runs()])
    def test_limit_is_clamped(self):
        for i in range(5):store.save_run(run_status("r%d"%i))
        self.assertEqual(2,len(store.list_runs(limit=2)))
        self.assertEqual(5,len(store.list_runs(limit="junk")))
    def test_history_is_bounded(self):
        old=store.RUNS_KEEP
        store.RUNS_KEEP=3
        try:
            for i in range(6):store.save_run(run_status("r%d"%i))
        finally:
            store.RUNS_KEEP=old
        self.assertEqual(["r5","r4","r3"],[r["run_id"] for r in store.list_runs()])
    def entry(self,seq,text="line",**data):
        return {"seq":seq,"ts":"2026-01-01T00:00:%02d+00:00"%seq,"node":"n1","title":"Node one","level":"info","kind":"command","text":text,"data":data}
    def test_run_log_rows_round_trip_in_order(self):
        self.assertEqual(2,store.append_run_log("r1",[self.entry(1,"first",job_key="k"),self.entry(2,"second")]))
        self.assertEqual(1,store.append_run_log("r1",[self.entry(3,"third")]))
        self.assertEqual(0,store.append_run_log("r1",[]))
        entries,total=store.get_run_log("r1")
        self.assertEqual(3,total)
        self.assertEqual([self.entry(1,"first",job_key="k"),self.entry(2,"second"),self.entry(3,"third")],entries)
        self.assertEqual(([3],3),([e["seq"] for e in store.get_run_log("r1",since=2)[0]],store.run_log_seq("r1")))
        self.assertEqual([1,2],[e["seq"] for e in store.get_run_log("r1",limit=2)[0]])
        self.assertEqual(([],0),store.get_run_log("other"));self.assertEqual(0,store.run_log_seq("other"))
    def test_logs_are_deleted_with_their_run_and_by_the_history_cap(self):
        old=store.RUNS_KEEP
        store.RUNS_KEEP=2
        try:
            store.append_run_log("live",[self.entry(1)])
            for i in range(4):
                store.append_run_log("r%d"%i,[self.entry(1)])
                store.save_run(run_status("r%d"%i,playbook_id=i))
        finally:
            store.RUNS_KEEP=old
        self.assertEqual([0,0,1,1],[store.get_run_log("r%d"%i)[1] for i in range(4)])
        self.assertEqual(1,store.get_run_log("live")[1],"a run that is still going keeps its log")
        self.assertTrue(store.delete_run("r3"));self.assertEqual(0,store.get_run_log("r3")[1])
        self.assertEqual(1,store.clear_runs(2));self.assertEqual(0,store.get_run_log("r2")[1])
        self.assertEqual(1,store.get_run_log("live")[1])
        self.assertTrue(store.delete_run("live"))
    def test_set_reviewed_can_clear_the_ai_made_flag(self):
        pid=chains.create_playbook("Demo")
        store.save_graph(pid,GRAPH,ai_made=True,ai_reviewed=False,ai_client="Claude")
        store.set_reviewed(pid,True)
        self.assertEqual((True,True),(store.get_graph_row(pid)["ai_made"],store.get_graph_row(pid)["ai_reviewed"]))
        store.set_reviewed(pid,True,clear_ai_made=True)
        self.assertEqual((False,True),(store.get_graph_row(pid)["ai_made"],store.get_graph_row(pid)["ai_reviewed"]))
    def test_an_oversized_snapshot_is_shrunk_not_refused(self):
        big="x"*(600*1024)
        nodes={"n%d"%i:{"state":"success","output":{"stdout":big,"stderr":big,"parsed":{"a":1},"trace":[1],"resolved":["echo hi"]}} for i in range(3)}
        store.save_run(run_status("big",nodes=nodes))
        saved=store.get_run("big")
        self.assertTrue(saved["truncated"])
        self.assertEqual("done",saved["state"])
        self.assertLessEqual(len(saved["nodes"]["n0"]["output"]["stdout"]),8192)
        self.assertTrue(saved["nodes"]["n0"]["output"]["stdout"].endswith("x") or saved["nodes"]["n0"]["output"]["stdout"]=="")
    def test_a_status_without_a_run_id_is_refused(self):
        with self.assertRaises(ValueError):store.save_run({"state":"done"})
if __name__=="__main__":unittest.main()
