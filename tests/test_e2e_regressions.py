"""Regressions found by the end-to-end test pass on demo data (B1-B11). Each test names the bug it guards."""
import json,os,sqlite3,sys,unittest
from contextlib import closing
sys.path.insert(0,os.path.dirname(os.path.abspath(__file__)))
from _isolate import IsolatedData
from Cores import common_db,recycle_bin
from Cores.Services import notes_service as ns,commands_service as cs,targets_service as ts,search_service as ss
from Cores.Bridge import api
def _card(d):
    t=ns._encode_cmd_data(d)
    return f'<a href="cmd:edit:{t}"><img src="cmdcard:{t}" width="320" height="90" /></a>'
def _marker(cid):return f'<span class="cmd-card-marker" data-cid="{cid}"></span>'
class _Base(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        self._abs=ns._abs
        ns._abs=lambda *p:os.path.join(self.dir,*(p[1:] if p and p[0]=="Data" else p))
        ns._SETTINGS_CACHE=None;ns._SETTINGS_MTIME=None
        self._stubs=[(api._semantic_svc,"index_note",api._semantic_svc.index_note),(api._semantic_svc,"remove_note",api._semantic_svc.remove_note),(api._semantic_svc,"index_command",api._semantic_svc.index_command),(api._semantic_svc,"remove_command",api._semantic_svc.remove_command),(api._targets_svc,"auto_add_target_values",api._targets_svc.auto_add_target_values)]
        for mod,name,_ in self._stubs:setattr(mod,name,lambda *a,**k:0)
        self.notes=api.NotesAPI();self.cmds=api.CommandsAPI()
        self.dbp=ns._db_path()
        with sqlite3.connect(self.dbp) as con:common_db.ensure_schema(con)
    def tearDown(self):
        for mod,name,fn in self._stubs:setattr(mod,name,fn)
        ns._abs=self._abs
        ns._SETTINGS_CACHE=None;ns._SETTINGS_MTIME=None
        self.iso.stop()
    def q(self,sql,args=()):
        with closing(sqlite3.connect(self.dbp)) as con:return con.execute(sql,args).fetchall()
    def save_with_card(self,note_id,name,data,extra=""):
        cid=data.get("cid") or "c1"
        return self.notes.save(note_id,name,"G","<p>body</p>"+extra+_marker(cid),[dict(data,cid=cid)],"")
CMD={"cmd_note_title":"Nikto","category":"Recon","sub_category":"Web","description":"","tags":"web","command":"nikto -h http://{IPv4}/","command_type":"Linux Shell"}
class LinkedCommandEditTests(_Base):
    # B2: editing a note-linked command on the Commands page must rewrite the card inside the note (editor cards carry cid/align/command_type).
    def test_commands_page_edit_updates_note_card_and_survives_next_note_save(self):
        nid=self.save_with_card(None,"Web",dict(CMD,cid="new-abc123"))["id"]
        row=[r for r in self.cmds.list() if r["src"]=="Commands"][0]
        self.cmds.update_linked(row,dict(cmd_note_title="Nikto full",category="Recon",sub_category="Web",description="",tags="web",command="nikto -C all -h http://{IPv4}/",command_type="Linux Shell"))
        cards=self.notes.edit_content(nid)["commands"]
        self.assertEqual(["nikto -C all -h http://{IPv4}/"],[c["command"] for c in cards])
        self.assertEqual("new-abc123",cards[0]["cid"])
        self.assertEqual("Nikto full",cards[0]["cmd_note_title"])
        # A later save of the note must not bring the old command back.
        ed=self.notes.edit_content(nid)
        self.notes.save(nid,"Web","G","<p>edited</p>"+_marker(cards[0]["cid"]),ed["commands"],"")
        self.assertEqual([("nikto -C all -h http://{IPv4}/",)],self.q("SELECT command FROM Commands WHERE note_id=?",(nid,)))
class NoteNameTests(_Base):
    # B3: a new note with an existing name must not overwrite that note.
    def test_new_note_with_existing_name_is_refused(self):
        nid=self.notes.save(None,"Reporting","","<p>original</p>",[],"")["id"]
        with self.assertRaises(ValueError):self.notes.save(None,"Reporting","","<p>other body</p>",[],"")
        self.assertIn("original",self.q("SELECT content FROM Notes WHERE id=?",(nid,))[0][0])
    def test_repeated_identical_new_save_is_a_no_op(self):
        a=self.notes.save(None,"Dbl","","<p>x</p>",[],"")
        b=self.notes.save(None,"Dbl","","<p>x</p>",[],"")
        self.assertEqual(a["id"],b["id"]);self.assertEqual("unchanged",b["action"])
        self.assertEqual(1,len(self.q("SELECT id FROM Notes WHERE note_name='Dbl'")))
    # B11: saving a note that was deleted while open must not silently drop the edits.
    def test_saving_a_deleted_note_recreates_it(self):
        nid=self.save_with_card(None,"Gone",CMD)["id"]
        self.notes.delete(nid)
        res=self.save_with_card(nid,"Gone",CMD,"<p>my edits</p>")
        self.assertNotEqual(nid,res["id"])
        self.assertIn("my edits",self.q("SELECT content FROM Notes WHERE id=?",(res["id"],))[0][0])
        self.assertEqual([(res["id"],)],self.q("SELECT note_id FROM Commands"))
class StableCommandIdTests(_Base):
    # B5: note saves keep the Commands row ids (favourites, playbooks, run history) and noise_level.
    def test_ids_and_noise_survive_note_edit_and_rename(self):
        two=[dict(CMD,cid="a"),dict(CMD,cid="b",cmd_note_title="Second",command="id")]
        nid=self.notes.save(None,"N","","<p>x</p>"+_marker("a")+_marker("b"),two,"")["id"]
        ids=[r[0] for r in self.q("SELECT id FROM Commands WHERE note_id=? ORDER BY id",(nid,))]
        with closing(sqlite3.connect(self.dbp)) as con,con:con.execute("UPDATE Commands SET noise_level='noisy' WHERE id=?",(ids[0],))
        edited=[dict(two[0]),dict(two[1],command="id -a")]
        self.notes.save(nid,"N renamed","","<p>changed</p>"+_marker("a")+_marker("b"),edited,"")
        rows=self.q("SELECT id,note_name,command,noise_level FROM Commands WHERE note_id=? ORDER BY id",(nid,))
        self.assertEqual(ids,[r[0] for r in rows])
        self.assertEqual(["N renamed","N renamed"],[r[1] for r in rows])
        self.assertEqual("id -a",rows[1][2]);self.assertEqual("noisy",rows[0][3])
    def test_removed_card_deletes_only_its_row(self):
        two=[dict(CMD,cid="a"),dict(CMD,cid="b",command="id")]
        nid=self.notes.save(None,"N","","<p>x</p>"+_marker("a")+_marker("b"),two,"")["id"]
        keep=self.q("SELECT id FROM Commands WHERE command='id'")[0][0]
        self.notes.save(nid,"N","","<p>x</p>"+_marker("b"),[two[1]],"")
        self.assertEqual([(keep,)],self.q("SELECT id FROM Commands WHERE note_id=?",(nid,)))
class RecycleTypeTests(_Base):
    # B4: command_type and noise_level survive delete -> restore, for note-linked and standalone commands.
    def test_note_restore_keeps_command_type(self):
        nid=self.save_with_card(None,"Typed",dict(CMD,command_type="PowerShell"))["id"]
        with closing(sqlite3.connect(self.dbp)) as con,con:con.execute("UPDATE Commands SET noise_level='stealthy'")
        self.notes.delete(nid)
        entry=recycle_bin.list_entries(self.dbp)[0]
        recycle_bin.restore_entry(entry["id"],self.dbp)
        self.assertEqual([("PowerShell","stealthy")],self.q("SELECT command_type,noise_level FROM Commands"))
    def test_standalone_restore_keeps_command_type(self):
        cid=self.cmds.create("SA","Win","AD","Get-ADUser -Filter *","ad","","PowerShell","noisy")["id"]
        self.cmds.delete(cid,"CommandsNotes")
        entry=recycle_bin.list_entries(self.dbp)[0]
        recycle_bin.restore_entry(entry["id"],self.dbp)
        self.assertEqual([("PowerShell","noisy")],self.q("SELECT command_type,noise_level FROM CommandsNotes"))
class WhitespaceTests(_Base):
    # B10: commands keep indentation and tabs in the Commands list (it feeds the edit form, Run and Copy).
    def test_list_keeps_indentation(self):
        raw="cat <<'EOF'\n  indented\tTAB\nEOF"
        self.cmds.create("SA","C","S",raw,"","","Linux Shell")
        self.assertEqual(raw,[r for r in self.cmds.list() if r["src"]=="CommandsNotes"][0]["command"])
        self.assertEqual(raw,ss._clean_cmd(raw))
    def test_legacy_html_is_still_flattened(self):
        self.assertEqual("nmap -sV",cs._clean_cmd("<p>nmap   -sV</p>"))
class PlaceholderTests(unittest.TestCase):
    # B1: shell variables, JSON and awk blocks are not target placeholders.
    def test_brace_edge_cases_are_not_keys(self):
        text="echo ${HOME} {} '{\"a\":1}' {{x}} awk '{print $1}' { $_.Name } {IPv4} {Target IP}"
        self.assertEqual(["IPv4","Target IP"],ts._extract_keys_from_text(text))
        self.assertEqual(["IPv4","Target IP"],[k for _,_,k in ss._iter_placeholders(text)])
    def test_rename_leaves_shell_variables_alone(self):
        self.assertEqual("echo ${HOME} {Home2}",ts._replace_placeholders("echo ${HOME} {HOME}",["HOME"],"Home2"))
class TargetKeyRenameTests(unittest.TestCase):
    # B6: renaming or merging a key moves every target's value to the new key on disk.
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        with sqlite3.connect(common_db.db_path()) as con:common_db.ensure_schema(con)
    def tearDown(self):self.iso.stop()
    def test_rename_moves_values(self):
        s=ts.Store();s.add_key("WebPort",0);s.upsert_target(None,"DC01","",{"WebPort":"8080"})
        self.assertTrue(s.rename_key("WebPort","HTTPPort")[0])
        self.assertEqual({"HTTPPort":"8080"},ts.Store().targets[0]["values"])
    def test_merge_moves_values(self):
        s=ts.Store();s.add_key("P1",0);s.upsert_target(None,"DC01","",{"P1":"1"})
        self.assertTrue(s.bulk_rename(["P1"],"Port")[0])
        self.assertEqual({"Port":"1"},ts.Store().targets[0]["values"])
if __name__=="__main__":unittest.main()
