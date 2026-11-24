import os,json,sqlite3,unittest
from unittest import mock
from _isolate import IsolatedData
from Cores import common_db
from Cores.Services import commands_service as cmds
from Cores.Services import targets_service as tsvc
class NormalizeTests(unittest.TestCase):
    def test_fields_and_tags(self):
        t,c,s,g=cmds.normalize_command_fields("  My   Title ","Recon\t Web"," sub  cat ","nmap; Scan ,nmap,  web   enum ,,SCAN")
        self.assertEqual(("My Title","Recon Web","sub cat"),(t,c,s))
        self.assertEqual("nmap,Scan,web enum",g)
    def test_empty_tags(self):
        self.assertEqual("",cmds.normalize_command_fields("a","b","c","")[3])
        self.assertEqual("",cmds.normalize_command_fields("a","b","c",None)[3])
    def test_validate_messages_spelled_right(self):
        self.assertEqual((False,"Command Note Title is required."),cmds.validate_command_fields("","c","s","ls"))
        self.assertEqual((True,""),cmds.validate_command_fields("t","c","s","ls"))
    def test_new_command_form_defaults_noise_to_normal(self):
        js=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","UI","js","pages","commands.js"),encoding="utf-8").read()
        new_branch=js.split('const h=cmdsState.history||{}',1)[1].split("}",1)[0]
        self.assertIn('#cmdsFieldNoise").value="normal"',new_branch)
    def test_command_field_overtypes_auto_closed_brace(self):
        js=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","UI","js","pages","commands.js"),encoding="utf-8").read()
        wire=js.split("function cmdsWireCommandSuggest(",1)[1].split("function cmdsWireTagSuggest(",1)[0]
        self.assertIn('ta.value.charAt(ta.selectionStart)==="}"',wire)
    def test_shell_pill_never_wraps(self):
        css=open(os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","UI","css","pages","notes.css"),encoding="utf-8").read()
        rule=css.split(".cmd-card-type{",1)[1].split("}",1)[0]
        self.assertIn("white-space:nowrap",rule)
class DbTests(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start();self.dbp=common_db.db_path()
    def tearDown(self):
        self.iso.stop()
    def _con(self):
        con=sqlite3.connect(self.dbp);common_db.ensure_schema(con);return con
    def test_sync_skips_missing_db(self):
        self.assertEqual(0,cmds._sync_missing_note_cmds(self.dbp))
        self.assertFalse(os.path.isfile(self.dbp))
    def test_sync_backfills_legacy_blocks(self):
        con=self._con()
        con.execute("INSERT INTO Notes(note_name,content) VALUES(?,?)",("Legacy","<p>x</p><C [Category: Recon, Sub Category: Web, Tags: a]> nmap {IP} </C>"))
        con.commit();con.close()
        self.assertEqual(1,cmds._sync_missing_note_cmds(self.dbp))
        self.assertEqual(0,cmds._sync_missing_note_cmds(self.dbp))
        _p,rows=cmds._load_cmds()
        self.assertEqual(["nmap {IP}"],[r["command"] for r in rows if r["src"]=="Commands"])
    def test_stamp_changes_on_insert_update_delete(self):
        self.assertEqual("",cmds.commands_stamp(self.dbp))
        cid=cmds._insert_cmd(self.dbp,"T","C","S","whoami","","")
        s1=cmds.commands_stamp(self.dbp)
        self.assertTrue(s1)
        self.assertEqual(s1,cmds.commands_stamp(self.dbp))
        con=self._con();con.execute("UPDATE CommandsNotes SET command='id',updated_at='2099-01-01' WHERE id=?",(cid,));con.commit();con.close()
        s2=cmds.commands_stamp(self.dbp)
        self.assertNotEqual(s1,s2)
        con=self._con();con.execute("DELETE FROM CommandsNotes");con.commit();con.close()
        self.assertNotEqual(s2,cmds.commands_stamp(self.dbp))
    def test_stamp_ignores_terminal_jobs(self):
        cmds._insert_cmd(self.dbp,"T","C","S","whoami","","")
        s1=cmds.commands_stamp(self.dbp)
        con=self._con();con.execute("INSERT INTO TerminalJobs(job_key,state,started_at) VALUES('k','running','now')");con.commit();con.close()
        self.assertEqual(s1,cmds.commands_stamp(self.dbp))
    def test_target_element_rows_rank_by_usage(self):
        cmds._insert_cmd(self.dbp,"A","C","S","nmap {IP} -p {Port}","","")
        cmds._insert_cmd(self.dbp,"B","C","S","ping {IP}","","")
        cmds._insert_cmd(self.dbp,"C","C","S","curl {URL}/{ip}","","")
        vals=os.path.join(self.dir,"tv.json");tg=os.path.join(self.dir,"tg.json")
        with open(vals,"w") as f:json.dump({"Domain":{"priority":5,"manual":True},"IP":{"priority":1}},f)
        with open(tg,"w") as f:json.dump([{"name":"box","values":{"Host":"h","IP":"1.2.3.4"}}],f)
        with mock.patch.object(tsvc,"_paths",lambda pid=None:(vals,tg)):
            rows=cmds.target_element_rows(self.dbp)
            keys=[r["key"] for r in rows]
            self.assertEqual("IP",keys[0])
            self.assertEqual(3,rows[0]["usage"])
            self.assertEqual("{IP}",rows[0]["token"])
            self.assertEqual(5,next(r for r in rows if r["key"]=="Domain")["priority"])
            self.assertEqual("targets",next(r for r in rows if r["key"]=="Host")["source"])
            self.assertEqual(len(keys),len({k.lower() for k in keys}))
            self.assertEqual(["Port"],[r["key"] for r in cmds.target_element_rows(self.dbp,"{po",3)])
            self.assertEqual(2,len(cmds.target_element_rows(self.dbp,"",2)))
    def test_history_last_fields(self):
        cmds._insert_cmd(self.dbp,"First","Cat1","Sub1","a","x, y","")
        cmds._insert_cmd(self.dbp,"Second","Cat2","Sub2","b","y;z","")
        h=cmds._history_from_db(self.dbp)
        self.assertEqual(("Second","Cat2","Sub2"),(h["last_note"],h["last_category"],h["last_subcategory"]))
        self.assertEqual(["x","y","z"],h["tags"])
class ApiTests(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.iso.start()
        from Cores.Bridge import api
        self.api=api
    def tearDown(self):
        self.iso.stop()
    def test_create_and_update_linked_normalize(self):
        c=self.api.CommandsAPI()
        c.create(" T  x ","Cat "," Sub","echo","a;b , A","d")
        self.assertEqual([("T x","Cat","Sub","a,b")],[(r["title"],r["category"],r["sub"],r["tags"]) for r in c.list()])
        con=sqlite3.connect(common_db.db_path());con.execute("INSERT INTO Notes(note_name,content) VALUES('L','<C [Category: K, Sub Category: S]>ls</C>')");con.commit();con.close()
        self.assertEqual(2,len(self.api.SearchAPI().list()))
        row=[r for r in c.list() if r["src"]=="Commands"][0]
        self.assertTrue(c.update_linked(row,{"cmd_note_title":" New  T","category":"K","sub_category":"S","tags":"q; q ,w","command":"ls -la"}))
        self.assertEqual([("New T","q,w")],[(r["title"],r["tags"]) for r in c.list() if r["src"]=="Commands"])
        self.assertTrue(c.stamp())
if __name__=="__main__":unittest.main()
