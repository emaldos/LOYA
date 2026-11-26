import os,sys,unittest,sqlite3,json,zipfile
from contextlib import closing
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from Cores import recycle_bin as rb
from Cores.Services import notes_service as ns
from Cores.Services import commands_service as cs
from Cores.Services import settings_service as ss
from Cores.Services import templates_service as ts
from Cores.Update import update_service as us
def _card(d):
    t=ns._encode_cmd_data(d)
    return f'<a href="cmd:edit:{t}"><img src="cmdcard:{t}" width="320" height="90" /></a>'
class _Base(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        self._abs=ns._abs
        ns._abs=lambda *p:os.path.join(self.dir,*(p[1:] if p and p[0]=="Data" else p))
        ns._SETTINGS_CACHE=None;ns._SETTINGS_MTIME=None
        self.dbp=ns._db_path()
    def tearDown(self):
        ns._abs=self._abs
        ns._SETTINGS_CACHE=None;ns._SETTINGS_MTIME=None
        self.iso.stop()
    def path(self,name,data=None):
        p=os.path.join(self.dir,name)
        if data is not None:
            with open(p,"w",encoding="utf-8") as f:f.write(data if isinstance(data,str) else json.dumps(data))
        return p
    def q(self,sql,args=()):
        with closing(sqlite3.connect(self.dbp)) as con:return con.execute(sql,args).fetchall()
class CommandsImportTest(_Base):
    def add(self,note,cat,sub,cmd,tags=""):return cs._insert_cmd(self.dbp,note,cat,sub,cmd,tags,"")
    # S3
    def test_dedup_key_is_command_text(self):
        a=self.add("Recon","Scan","TCP","nmap -sV {IP}")
        b=self.add("Recon","Scan","TCP","nmap -p- {IP}")
        ce=cs.CommandsExport()
        plan=ce.build_plan(ce.rows([{"note_name":"Other","category":"X","sub_category":"Y","command":"  NMAP   -p-  {ip} ","tags":"t","description":""}]),ce.load())
        self.assertEqual(len(plan["dups"]),1)
        self.assertEqual(plan["dups"][0]["existing"]["id"],b)
        res=cs.CommandsExport().apply_plan(plan,{0:"Replace"})
        self.assertEqual(res["replaced"],1)
        self.assertEqual(self.q("SELECT command FROM CommandsNotes WHERE id=?",(a,))[0][0],"nmap -sV {IP}")
        self.assertEqual(self.q("SELECT note_name,command FROM CommandsNotes WHERE id=?",(b,))[0],("Other","  NMAP   -p-  {ip}"))
    def test_same_note_category_is_not_a_conflict(self):
        self.add("Recon","Scan","TCP","nmap -sV {IP}")
        ce=cs.CommandsExport()
        plan=ce.build_plan([{"note_name":"Recon","category":"Scan","sub_category":"TCP","command":"masscan {IP}"}],ce.load())
        self.assertEqual((len(plan["new"]),len(plan["dups"])),(1,0))
    # S4
    def test_overwrite_replaces_row_and_recycles_old(self):
        a=self.add("Recon","Scan","TCP","whoami","old")
        ce=cs.CommandsExport()
        plan=ce.build_plan([{"note_name":"N","command":"whoami","tags":"new"}],ce.load())
        res=cs.CommandsExport().apply_plan(plan,{0:"Overwrite"})
        self.assertEqual(res["overwritten"],1)
        rows=self.q("SELECT id,tags FROM CommandsNotes")
        self.assertEqual(len(rows),1);self.assertNotEqual(rows[0][0],a);self.assertEqual(rows[0][1],"new")
        self.assertEqual(len(rb.list_entries(entity_type="command")),1)
    def test_bad_rows_are_counted(self):
        ce=cs.CommandsExport()
        plan=ce.build_plan([{"note_name":"a","command":"one"},{"note_name":"b","command":"two"}],[])
        orig=cs._insert_cmd
        def boom(dbp,note,*a,**k):
            if note=="b":raise sqlite3.OperationalError("disk full")
            return orig(dbp,note,*a,**k)
        cs._insert_cmd=boom
        try:res=cs.CommandsExport().apply_plan(plan,{})
        finally:cs._insert_cmd=orig
        self.assertEqual((res["added"],res["bad"]),(1,1))
    def test_invalid_and_repeated_rows(self):
        p=self.path("c.json",[{"note_name":"a","command":"x"},{"note_name":"a","command":" "},{"note_name":"b","command":"X"},"junk"])
        ce=cs.CommandsExport();rows=ce.parse_json(p);plan=ce.build_plan(rows,[])
        self.assertEqual(len(plan["new"]),1);self.assertEqual(plan["invalid"],3)
    # S2
    def test_parse_both_shapes(self):
        lst=self.path("l.json",[{"note_name":"a","command":"id"}])
        dct=self.path("d.json",{"CommandsNotes":[{"note_name":"a","command":"id"}],"Notes":[]})
        self.assertEqual(len(cs.CommandsExport().parse_json(lst)),1)
        self.assertEqual(len(cs.CommandsExport().parse_json(dct)),1)
        self.assertEqual(len(cs.CommandsExport().parse_json(self.path("t.json",ts.human_commands_json()))),1)
    def test_type_and_noise_round_trip(self):
        cs._insert_cmd(self.dbp,"n","c","s","rm -rf /tmp/x","","","cleanup","destructive")
        ce=cs.CommandsExport();p=self.path("e.json");ce.export_json(p,ce.load())
        self.assertEqual(json.load(open(p))[0]["noise_level"],"destructive")
        plan=ce.build_plan(ce.parse_json(p),ce.load())
        cs.CommandsExport().apply_plan(plan,{0:"Replace"})
        self.assertEqual(self.q("SELECT command_type,noise_level FROM CommandsNotes")[0],("cleanup","destructive"))
class NotesImportTest(_Base):
    def save(self,name,content="<p>x</p>",tags=""):
        return ns.save_note(self.dbp,None,name,"",content,ns.extract_editor_cmd_cards(content),tags)[0]
    # S4
    def test_replace_keeps_id_overwrite_makes_new(self):
        a=self.save("A");b=self.save("B")
        ne=ns.NotesExport()
        plan=ne.build_plan([{"note_name":"a","group_name":"","tags":"","content":"<p>1</p>"},{"note_name":"B","group_name":"","tags":"","content":"<p>2</p>"}],ne.load())
        res=ns.NotesExport().apply_plan(plan,{0:"Replace",1:"Overwrite"})
        self.assertEqual((res["replaced"],res["overwritten"],res["bad"]),(1,1,0))
        self.assertEqual(self.q("SELECT id,content FROM Notes WHERE note_name='A'")[0],(a,"<p>1</p>"))
        nb=self.q("SELECT id,content FROM Notes WHERE note_name='B'")[0]
        self.assertNotEqual(nb[0],b);self.assertEqual(nb[1],"<p>2</p>")
        self.assertEqual(len(rb.list_entries(entity_type="note")),1)
    def test_bad_note_row_counted(self):
        ne=ns.NotesExport();plan=ne.build_plan([{"note_name":"A","content":""},{"note_name":"B","content":""}],[])
        orig=ns.save_note
        def boom(dbp,nid,name,*a,**k):
            if name=="B":raise sqlite3.OperationalError("locked")
            return orig(dbp,nid,name,*a,**k)
        ns.save_note=boom
        try:res=ns.NotesExport().apply_plan(plan,{})
        finally:ns.save_note=orig
        self.assertEqual((res["added"],res["bad"]),(1,1))
    # S2
    def test_ng_template_imports_note_and_command(self):
        ne=ns.NotesExport();rows=ne.parse_json(self.path("t.json",ts.human_notes_json()))
        self.assertEqual([r["note_name"] for r in rows],["Example Note"])
        self.assertEqual(len(ne.commands),1)
        plan=ne.build_plan(rows,ne.load())
        res=ns.NotesExport().apply_plan(plan,{})
        self.assertEqual(res["added"],2)
        self.assertEqual(self.q("SELECT command FROM CommandsNotes"),[("echo hello",)])
        self.assertEqual(self.q("SELECT cmd_note_title,command FROM Commands"),[("Example Command","echo hello")])
        content=self.q("SELECT content FROM Notes")[0][0]
        self.assertIn("cmdcard:",content);self.assertNotIn("&lt;C",content);self.assertNotIn("<C [",content)
    def test_original_dict_and_list_shapes(self):
        d={"Notes":[{"id":3,"note_name":"N1","group_name":"G","content":"&lt;C [Command Note Tittle: T, Category: Rec, Tags: web] &gt;<br>curl {URL}<br>&lt;/C&gt;"}],"CommandsNotes":[{"note_name":"x","command":"ls"}],"Commands":[{"note_id":3,"command":"curl {URL}"}]}
        ne=ns.NotesExport();rows=ne.parse_json(self.path("o.json",d))
        self.assertEqual(len(rows),1);self.assertEqual(len(ne.commands),1)
        card=ns.extract_editor_cmd_cards(rows[0]["content"])
        self.assertEqual([(c["cmd_note_title"],c["category"],c["tags"],c["command"]) for c in card],[("T","Rec","web","curl {URL}")])
        ne2=ns.NotesExport();rows2=ne2.parse_json(self.path("l.json",[{"note_name":"Z","content":"<p>z</p>"},{"note_name":"c","command":"pwd"}]))
        self.assertEqual(([r["note_name"] for r in rows2],len(ne2.commands)),(["Z"],1))
        with self.assertRaises(ValueError):ns.NotesExport().parse_json(self.path("bad.json","\"text\""))
    def test_command_conflicts_share_one_decision_list(self):
        cs._insert_cmd(self.dbp,"x","","","ls","","")
        self.save("N1")
        ne=ns.NotesExport();rows=ne.parse_json(self.path("o.json",{"Notes":[{"note_name":"N1","content":"<p>new</p>"}],"CommandsNotes":[{"note_name":"y","command":"ls","tags":"t2"}]}))
        plan=ne.build_plan(rows,ne.load())
        self.assertEqual([d["table"] for d in plan["dups"]],["Notes","CommandsNotes"])
        res=ns.NotesExport().apply_plan(plan,{0:"Skip",1:"Replace"})
        self.assertEqual((res["skipped"],res["replaced"]),(1,1))
        self.assertEqual(self.q("SELECT note_name,tags FROM CommandsNotes"),[("y","t2")])
        self.assertEqual(self.q("SELECT content FROM Notes")[0][0],"<p>x</p>")
    # S8
    def test_all_tables_formats_round_trip(self):
        self.save("N1","<p>a</p>"+_card({"cmd_note_title":"t","command":"id"}),"red")
        cs._insert_cmd(self.dbp,"x","","","uname -a","","")
        ne=ns.NotesExport()
        pj=self.path("a.json");pz=self.path("a.zip");pd=self.path("a.db")
        ne.export_json_all(pj);ne.export_csv_zip(pz);ne.export_db(pd)
        self.assertEqual(sorted(json.load(open(pj)).keys()),["Commands","CommandsNotes","Notes"])
        with zipfile.ZipFile(pz) as z:self.assertEqual(sorted(z.namelist()),["Commands.csv","CommandsNotes.csv","Notes.csv"])
        for fn,p in (("parse_json",pj),("parse_csv_zip",pz),("parse_db",pd)):
            n=ns.NotesExport();rows=getattr(n,fn)(p)
            self.assertEqual([(r["note_name"],r["tags"]) for r in rows],[("N1","red")],fn)
            self.assertEqual([c["command"] for c in n.commands],["uname -a"],fn)
        with self.assertRaises(ValueError):ns.NotesExport().parse_db(pj)
class RecycleAndTagsTest(_Base):
    # S12
    def test_note_tags_survive_recycle_restore(self):
        ns.save_note(self.dbp,None,"T","","<p>x</p>",[],"red,blue")
        self.assertTrue(ns._delete_note(self.dbp,"T"))
        e=rb.list_entries(entity_type="note")[0]
        self.assertEqual(rb.restore_entry(e["id"]),(True,"Restored"))
        self.assertEqual(self.q("SELECT tags FROM Notes WHERE note_name='T'")[0][0],"red,blue")
    def test_purge_all_ignores_filter(self):
        rb.put_entry("note","a",{"note":{"note_name":"a"}});rb.put_entry("command","b",{"command":{}})
        self.assertEqual(rb.purge_all(),2);self.assertEqual(rb.list_entries(),[])
    # S11
    def test_restore_many_reports_failures(self):
        from Cores.Bridge import api
        ns.save_note(self.dbp,None,"Dup","","<p>x</p>",[],"")
        ok1,id1=rb.put_entry("note","Dup",{"note":{"note_name":"Dup"}})
        ok2,id2=rb.put_entry("note","Fresh",{"note":{"note_name":"Fresh"}})
        res=api.RecycleBinAPI().restore_many([id1,id2])
        self.assertEqual(res["ok"],1)
        self.assertEqual([(f["label"],f["error"]) for f in res["failed"]],[("Dup","A note with the same name already exists.")])
    # S13 / S23
    def test_tag_manager_counts_and_renames_note_tags_and_cards(self):
        content="<p>x</p>"+_card({"cmd_note_title":"t","command":"id","tags":"Web,other"})+"<p>&lt;C [Command Note Tittle: L, Tags: web] &gt;</p>"
        ns.save_note(self.dbp,None,"N","",content,ns.extract_editor_cmd_cards(content),"web, red")
        cs._insert_cmd(self.dbp,"x","","","ls","web","")
        tm=ss.TagManager()
        row=[r for r in tm.load_summary() if r["tag"].lower()=="web"][0]
        self.assertEqual((row["commands_notes"],row["linked"],row["notes_tagged"],row["total"]),(1,1,1,3))
        res=tm.update_tags("rename",["web"],"http",include_linked=True)
        self.assertEqual((res["commands_notes"],res["note_tags"],res["linked"],res["notes"]),(1,1,1,1))
        self.assertEqual(self.q("SELECT tags FROM Notes")[0][0],"http,red")
        new_content=self.q("SELECT content FROM Notes")[0][0]
        self.assertEqual([c["tags"] for c in ns.extract_editor_cmd_cards(new_content)],["http,other"])
        self.assertIn("Tags: http]",new_content)
        self.assertNotIn("web",[r["tag"].lower() for r in tm.load_summary()])
    def test_tag_delete_without_linked_keeps_cards(self):
        content=_card({"cmd_note_title":"t","command":"id","tags":"web"})
        ns.save_note(self.dbp,None,"N","",content,ns.extract_editor_cmd_cards(content),"web")
        res=ss.TagManager().update_tags("delete",["web"],"",include_linked=False)
        self.assertEqual((res["note_tags"],res["notes"],res["linked"]),(1,0,0))
        self.assertEqual(self.q("SELECT content FROM Notes")[0][0],content)
class ExportAllAndUpdateTest(_Base):
    def test_export_all_manifest_and_info(self):
        with open(os.path.join(self.dir,"x.json"),"w") as f:f.write("{}")
        orig=ss._health_check.data_dir;ss._health_check.data_dir=lambda:self.dir
        try:
            out=os.path.join(self.dir,"out","LOYA_All_export.zip");n=ss.export_all_zip(out)
        finally:ss._health_check.data_dir=orig
        with zipfile.ZipFile(out) as z:
            names=z.namelist();man=json.loads(z.read("manifest.json"))
        # Export my work is built from an allowlist: an unknown Data/ file never goes in, and nothing sits under Data/.
        self.assertEqual("loya-work-export",man["format"]);self.assertEqual(len(names),n)
        self.assertFalse([x for x in names if x.endswith("x.json") or x.startswith("Data/")],names)
        self.assertIn("content.db",names);self.assertEqual(ss.import_all_info(out),sum(man["counts"].values()))
        empty=os.path.join(self.dir,"e.zip")
        with zipfile.ZipFile(empty,"w") as z:z.writestr("readme.txt","x")
        self.assertEqual(ss.import_all_info(empty),0)
    # S18
    def test_save_update_settings_keeps_last_checked(self):
        orig=us._settings_path;us._settings_path=lambda:os.path.join(self.dir,"settings.json")
        try:
            us.save_update_settings({"auto_enabled":True,"check_interval_hours":24,"last_checked":"2026-01-01T00:00:00Z"})
            us.save_update_settings({"auto_enabled":False,"check_interval_hours":72,"last_channel":"stable"})
            cfg=us.get_update_settings()
        finally:us._settings_path=orig
        self.assertEqual((cfg["last_checked"],cfg["auto_enabled"],cfg["check_interval_hours"]),("2026-01-01T00:00:00Z",False,72))
if __name__=="__main__":unittest.main()
