import os,sys,unittest,sqlite3,re
from contextlib import closing
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from Cores.Services import notes_service as ns
from Cores.Bridge import api
def _token(d):return ns._encode_cmd_data(d)
def _card(d):
    t=_token(d)
    return f'<a href="cmd:edit:{t}"><img src="cmdcard:{t}" width="320" height="90" /></a>'
class NotesIntegrityTest(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        self._abs=ns._abs
        ns._abs=lambda *p:os.path.join(self.dir,*(p[1:] if p and p[0]=="Data" else p))
        ns._SETTINGS_CACHE=None;ns._SETTINGS_MTIME=None
        self._stubs=[(api._semantic_svc,"index_note",api._semantic_svc.index_note),(api._semantic_svc,"remove_note",api._semantic_svc.remove_note),(api._targets_svc,"auto_add_target_values",api._targets_svc.auto_add_target_values)]
        for mod,name,_ in self._stubs:setattr(mod,name,lambda *a,**k:0)
        self.api=api.NotesAPI()
        self.dbp=ns._db_path()
    def tearDown(self):
        for mod,name,fn in self._stubs:setattr(mod,name,fn)
        ns._abs=self._abs
        ns._SETTINGS_CACHE=None;ns._SETTINGS_MTIME=None
        self.iso.stop()
    def cmds(self,nid):
        with closing(sqlite3.connect(self.dbp)) as con,con:
            return [r[0] for r in con.execute("SELECT command FROM Commands WHERE note_id=? ORDER BY id",(nid,))]
    def raw_insert(self,name,content):
        with closing(sqlite3.connect(self.dbp)) as con,con:
            ns._ensure_schema(con)
            cur=con.execute("INSERT INTO Notes(note_name,group_name,content,created_at,updated_at) VALUES(?,?,?,?,?)",(name,"",content,"2024-01-01","2024-01-01"))
            return cur.lastrowid
    def raw_cmd(self,nid,name,command):
        with closing(sqlite3.connect(self.dbp)) as con,con:
            con.execute("INSERT INTO Commands(note_id,note_name,cmd_note_title,category,sub_category,description,tags,command,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",(nid,name,"t","c","s","","",command,"x","x"))
    # N1
    def test_append_keeps_commands(self):
        r=self.api.save(None,"A","","<p>x</p>"+_card({"cmd_note_title":"t","command":"nmap -sV {IP}"}),[],"")
        self.assertEqual(self.cmds(r["id"]),["nmap -sV {IP}"])
        self.api.append(r["id"],"<p>more</p>")
        self.assertEqual(self.cmds(r["id"]),["nmap -sV {IP}"])
        self.api.append(r["id"],self.api.command_block_html("t2","c","s","whoami"))
        self.assertEqual(self.cmds(r["id"]),["nmap -sV {IP}","whoami"])
    def test_mcp_style_save_with_empty_cmds_keeps_cards(self):
        r=self.api.save(None,"B","","<p>x</p>"+self.api.command_block_html("t","c","s","id"),[],"")
        self.assertEqual(self.cmds(r["id"]),["id"])
        self.api.save(r["id"],"B","","<p>y</p>"+self.api.command_block_html("t","c","s","id"),[],"")
        self.assertEqual(self.cmds(r["id"]),["id"])
    def test_editor_save_rebuilds_from_cards(self):
        r=self.api.save(None,"C","",'<p>a</p><span class="cmd-card-marker" data-cid="new-1"></span>',[{"cid":"new-1","cmd_note_title":"t","command":"ls -la"}],"")
        self.assertEqual(self.cmds(r["id"]),["ls -la"])
        ed=self.api.edit_content(r["id"])
        self.assertEqual([c["command"] for c in ed["commands"]],["ls -la"])
        self.assertIn("cmd-card-embed",ed["content_html"])
    # N2
    def test_legacy_c_block_converted_and_kept(self):
        nid=self.raw_insert("Old","<p>&lt;C [Category: Recon, Sub Category: Ports]&gt;</p><p>nmap -p- {IP}</p><p>&lt;/C&gt;</p>")
        self.raw_cmd(nid,"Old","nmap -p- {IP}")
        ed=self.api.edit_content(nid)
        self.assertEqual(len(ed["commands"]),1)
        self.assertEqual(ed["commands"][0]["command"],"nmap -p- {IP}")
        self.assertEqual(ed["commands"][0]["category"],"Recon")
        self.assertEqual(ed["commands"][0]["cmd_note_title"],"Old")
        self.assertNotIn("&lt;C",ed["content_html"])
        # the editor posts its cards back as markers
        cmds=[dict(c) for c in ed["commands"]]
        html_in=ed["content_html"]
        for c in cmds:
            html_in=re.sub(r'<div class="cmd-card cmd-card-embed.*?</pre></div>',f'<span class="cmd-card-marker" data-cid="{c["cid"]}"></span>',html_in,count=1,flags=re.S)
        self.api.save(nid,"Old","",html_in,cmds,"")
        self.assertEqual(self.cmds(nid),["nmap -p- {IP}"])
    def test_legacy_cmdedit_anchor_and_table(self):
        d={"cmd_note_title":"T","category":"c","command":"whoami /all"}
        t=_token(d)
        anchor=f'<p><a href="cmdedit:{t}"><img src="cmdcard:{t}" width="560" height="140" /></a></p>'
        table=f'<table border="0"><tr><td><p>id</p></td><td><a href="cmdedit:{_token({"command":"id"})}">Edit</a> <a href="cmddelete:x">Del</a></td></tr></table>'
        nid=self.raw_insert("Legacy",f"<!DOCTYPE HTML><html><head><style>p{{white-space:pre-wrap}}</style></head><body style=\"x\">{anchor}{table}</body></html>")
        ed=self.api.edit_content(nid)
        self.assertEqual(sorted(c["command"] for c in ed["commands"]),["id","whoami /all"])
        self.assertNotIn("<style",ed["content_html"]);self.assertNotIn("<table",ed["content_html"])
        view=self.api.get(nid)["content_html"]
        self.assertEqual(view.count('class="cmd-card"'),2)
        self.assertNotIn("cmdedit:",view)
    def test_db_only_commands_appear_and_survive_save(self):
        nid=self.raw_insert("DbOnly","<p>plain text</p>")
        self.raw_cmd(nid,"DbOnly","cat /etc/passwd")
        self.assertIn("cat /etc/passwd",self.api.get(nid)["content_html"])
        ed=self.api.edit_content(nid)
        self.assertEqual([c["command"] for c in ed["commands"]],["cat /etc/passwd"])
        self.api.append(nid,"<p>more</p>")
        self.assertEqual(self.cmds(nid),["cat /etc/passwd"])
    # N21
    def test_empty_note_rejected_and_unchanged_skipped(self):
        with self.assertRaises(ValueError):self.api.save(None,"E","","<p> </p>",[],"")
        r=self.api.save(None,"E","","<p>body</p>",[],"")
        r2=self.api.save(r["id"],"E","","<p>body</p>",[],"")
        self.assertEqual(r2["action"],"unchanged")
        self.assertEqual(len(ns.list_versions(r["id"])),1)
    def test_rename_to_existing_name_is_a_clear_error(self):
        self.api.save(None,"One","","<p>1</p>",[],"")
        r=self.api.save(None,"Two","","<p>2</p>",[],"")
        with self.assertRaises(ValueError) as cm:self.api.save(r["id"],"One","","<p>2</p>",[],"")
        self.assertIn("already exists",str(cm.exception))
    # N15
    def test_soft_delete_keeps_attachments(self):
        att=self.api.insert_attachment("a.png","data:image/png;base64,iVBORw0KGgo=")
        body=f'<figure class="note-embed" data-attachment-id="{att["id"]}"><img src="{att["url"]}"></figure>'
        r=self.api.save(None,"Img","",body,[],"")
        with closing(sqlite3.connect(self.dbp)) as con,con:content=con.execute("SELECT content FROM Notes WHERE id=?",(r["id"],)).fetchone()[0]
        self.assertIn(f"Attachments/{r['id']}/",content)
        self.assertEqual(len(ns.list_versions(r["id"])),1)
        folder=os.path.join(ns._attachments_root(),str(r["id"]))
        self.assertTrue(os.path.isdir(folder))
        self.api.delete(r["id"])
        self.assertTrue(os.path.isdir(folder))
        with closing(sqlite3.connect(self.dbp)) as con,con:con.execute("DELETE FROM RecycleBin")
        ns.purge_orphan_attachments(self.dbp)
        self.assertFalse(os.path.isdir(folder))
    def test_permanent_delete_from_recycle_bin_removes_orphan_files(self):
        from Cores import recycle_bin as rb
        att=self.api.insert_attachment("b.png","data:image/png;base64,iVBORw0KGgo=")
        r=self.api.save(None,"Img2","",f'<figure class="note-embed" data-attachment-id="{att["id"]}"><img src="{att["url"]}"></figure>',[],"")
        folder=os.path.join(ns._attachments_root(),str(r["id"]))
        self.api.delete(r["id"])
        entry=[e for e in rb.list_entries(self.dbp) if e["label"]=="Img2"][0]
        self.assertTrue(os.path.isdir(folder),"the bin entry still needs the files for a restore")
        self.assertEqual((True,"Deleted permanently"),rb.delete_entry(entry["id"],self.dbp))
        self.assertFalse(os.path.isdir(folder))
        self.assertEqual((False,"Not found"),rb.delete_entry(entry["id"],self.dbp))
    # N9
    def test_note_images_paths_rewritten(self):
        d=os.path.join(self.dir,"NoteImages");os.makedirs(d,exist_ok=True)
        with open(os.path.join(d,"note_1.png"),"wb") as f:f.write(b"x")
        out=ns.rewrite_legacy_image_paths('<img src="C:\\Old\\LOYA\\Data\\NoteImages\\note_1.png" width="10" />')
        self.assertIn("file:///",out);self.assertIn("note_1.png",out);self.assertNotIn("C:\\Old",out)
        keep='<img src="/nowhere/NoteImages/missing.png" />'
        self.assertEqual(ns.rewrite_legacy_image_paths(keep),keep)
    # N11
    def test_name_only_and_stale_links_resolve(self):
        a=self.api.save(None,"Target Note","","<p>t</p>",[],"")
        tok=ns._encode_note_link_data({"note_name":"target note"})
        stale=ns._encode_note_link_data({"note_id":9999,"note_name":"Target Note"})
        r=self.api.save(None,"Src","",f'<p><a href="notelink:{tok}">x</a> <a href="notelink:{stale}">y</a></p>',[],"")
        view=self.api.get(r["id"])["content_html"]
        self.assertEqual(view.count(f'data-note-id="{a["id"]}"'),2)
        with closing(sqlite3.connect(self.dbp)) as con,con:content=con.execute("SELECT content FROM Notes WHERE id=?",(r["id"],)).fetchone()[0]
        for m in ns._NOTE_LINK_TOKEN_RX.finditer(content):self.assertEqual(ns._decode_note_link_data(m.group(1))["note_id"],a["id"])
    def test_notename_ref_text(self):
        a=self.api.save(None,"Recon","","<p>t</p>",[],"")
        r=self.api.save(None,"Ref","","<p>see -Notename-Recon- and -Notename-Nope-</p>",[],"")
        view=self.api.get(r["id"])["content_html"]
        self.assertIn(f'data-note-id="{a["id"]}"',view);self.assertIn("note-ref-missing",view)
    # N4 / N22
    def test_group_manager(self):
        a=self.api.save(None,"G1","Old","<p>1</p>",[],"")
        self.api.create_group("Empty")
        names=[g["group_name"] for g in self.api.groups()]
        self.assertIn("Empty",names)
        self.api.rename_group("Old","New")
        self.assertEqual(self.api.get(a["id"])["group_name"],"New")
        with self.assertRaises(ValueError):self.api.delete_group("New")
        self.api.move_note(a["id"],"")
        self.assertEqual(self.api.get(a["id"])["group_name"],"")
        self.assertTrue(self.api.delete_group("Empty"))
        self.assertNotIn("Empty",[g["group_name"] for g in self.api.groups()])
        self.api.set_group_collapsed("New",True);self.api.set_group_collapsed("",True)
        st={g["group_name"]:g["collapsed"] for g in self.api.groups()}
        self.assertTrue(st["New"]);self.assertTrue(st[""])
        self.api.set_group_collapsed("New",False)
        self.assertFalse({g["group_name"]:g["collapsed"] for g in self.api.groups()}["New"])
    # S15
    def test_editor_prefs(self):
        p=self.api.editor_prefs()
        self.assertEqual(p["cmd_box_command_height"],86)
        self.assertEqual(self.api.set_editor_pref("cmd_box_command_height",500)["cmd_box_command_height"],180)
        self.assertEqual(self.api.set_editor_pref("note_text_color","#112233")["note_text_color"],"#112233")
        with self.assertRaises(ValueError):self.api.set_editor_pref("bogus",1)
if __name__=="__main__":unittest.main()
