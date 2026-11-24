import json,os,sqlite3,sys,time,unittest
from _isolate import ROOT,IsolatedData
from Cores import common_db,recycle_bin,target_profiles
from Cores.Services import targets_service as ts
try:
    from Cores.Bridge import api
except Exception:
    api=None
def _add_command(table,command):
    with sqlite3.connect(common_db.db_path()) as con:
        common_db.ensure_schema(con)
        con.execute(f"INSERT INTO {table}(note_name,category,sub_category,command,tags) VALUES(?,?,?,?,?)",("n","c","s",command,""))
        con.commit()
def _bump(path):
    st=os.stat(path);os.utime(path,ns=(st.st_atime_ns,st.st_mtime_ns+1_000_000))
class _Isolated(unittest.TestCase):
    def setUp(self):
        self.iso=IsolatedData();self.dir=self.iso.start()
        with sqlite3.connect(common_db.db_path()) as con:common_db.ensure_schema(con)
    def tearDown(self):self.iso.stop()
class AddKeyTests(_Isolated):
    def test_keys_are_kept_exactly_as_typed(self):
        s=ts.Store()
        for k in ("ip","user","target"):self.assertEqual((True,"Added"),s.add_key(k,0))
        self.assertEqual({"ip","user","target"},set(ts.Store().values))
    def test_braces_are_stripped_and_case_insensitive_duplicates_rejected(self):
        s=ts.Store()
        self.assertTrue(s.add_key("{URL}",0)[0])
        self.assertIn("URL",s.values)
        ok,msg=s.add_key("url",0)
        self.assertFalse(ok);self.assertIn("'URL'",msg)
    def test_rename_strips_braces(self):
        s=ts.Store();s.add_key("ip",0)
        self.assertTrue(s.rename_key("ip","{Host}")[0])
        self.assertIn("Host",ts.Store().values)
class AutoAddTests(_Isolated):
    def test_new_keys_in_both_command_tables_are_registered(self):
        _add_command("Commands","nmap {RHOST}")
        _add_command("CommandsNotes","curl {URL}/{rhost}")
        self.assertEqual(2,ts.Store().auto_added)
        s=ts.Store()
        self.assertEqual(0,s.auto_added)
        self.assertEqual({"RHOST","URL"},set(s.values))
    def test_helper_reports_what_it_added_and_never_raises(self):
        ts.Store()
        _add_command("CommandsNotes","ssh {User}@{IP}")
        self.assertEqual(2,ts.auto_add_target_values())
        self.assertEqual(0,ts.auto_add_target_values())
        orig=ts.Store
        def boom(*a,**k):raise RuntimeError("x")
        ts.Store=boom
        try:self.assertEqual(0,ts.auto_add_target_values())
        finally:ts.Store=orig
class RecycleRestoreTests(_Isolated):
    def test_restore_keeps_engagement_status_and_returns_to_its_profile(self):
        ok,msg,pid=target_profiles.create_profile("Client B")
        self.assertTrue(ok)
        target_profiles.switch_profile(pid)
        s=ts.Store();s.upsert_target(None,"web01","not_used",{},"compromised")
        tid=s.targets[0]["id"]
        self.assertTrue(s.delete_target(tid)[0])
        target_profiles.switch_profile(target_profiles.DEFAULT_PROFILE_ID)
        with sqlite3.connect(common_db.db_path()) as con:eid=con.execute("SELECT id FROM RecycleBin ORDER BY id DESC").fetchone()[0]
        self.assertEqual((True,"Restored"),recycle_bin.restore_entry(eid))
        self.assertEqual([],ts.Store().targets)
        restored=ts.Store(pid).targets
        self.assertEqual(["web01"],[t["name"] for t in restored])
        self.assertEqual("compromised",restored[0]["engagement_status"])
    def test_restore_of_a_deleted_profile_falls_back_to_the_active_one(self):
        recycle_bin._restore_target({"target":{"id":"abc","name":"db01","status":"live","values":{"IP":"1.2.3.4"}},"profile_id":"gone"})
        rows=ts._read_json(ts._paths()[1],[])
        self.assertEqual([("db01","live","not_started")],[(t["name"],t["status"],t["engagement_status"]) for t in rows])
@unittest.skipIf(api is None,"pywebview not installed for this interpreter")
class TargetsApiCacheTests(_Isolated):
    def test_new_keys_from_commands_appear_without_a_restart(self):
        t=api.TargetsAPI()
        self.assertEqual([],t.keys())
        _add_command("Commands","nmap -p {PORT} {IP}")
        self.assertEqual({"PORT","IP"},{k["key"] for k in t.keys()})
    def test_a_live_change_made_elsewhere_is_not_reverted_by_the_next_save(self):
        t=api.TargetsAPI()
        t.add_key("IP",0)
        t.upsert_target(None,"alpha","not_used",{"IP":"10.0.0.1"})
        t.upsert_target(None,"beta","not_used",{})
        alpha=next(x for x in t.targets() if x["name"]=="alpha")
        time.sleep(0.01)
        mini=ts.Store();mini.set_live_target(alpha["id"])
        _bump(mini.targets_path)
        beta=next(x for x in t.targets() if x["name"]=="beta")
        t.upsert_target(beta["id"],"beta","not_used",{"IP":"10.0.0.2"})
        on_disk={x["name"]:x for x in ts._read_json(mini.targets_path,[])}
        self.assertEqual("live",on_disk["alpha"]["status"])
        self.assertEqual("10.0.0.2",on_disk["beta"]["values"]["IP"])
    def test_a_recycle_bin_restore_shows_up(self):
        t=api.TargetsAPI()
        t.upsert_target(None,"gamma","not_used",{})
        gid=t.targets()[0]["id"]
        t.delete_target(gid)
        self.assertEqual([],t.targets())
        with sqlite3.connect(common_db.db_path()) as con:eid=con.execute("SELECT id FROM RecycleBin ORDER BY id DESC").fetchone()[0]
        recycle_bin.restore_entry(eid)
        _bump(ts._paths()[1])
        self.assertEqual(["gamma"],[x["name"] for x in t.targets()])
class _Win:
    uid="mini"
    def __init__(self,x=5,y=6,w=520,h=420):
        class _E:
            def __iadd__(self,f):return self
        class _Ev:pass
        self.events=_Ev()
        for n in ("moved","resized","closing","shown"):setattr(self.events,n,_E())
        self.x,self.y,self.width,self.height=x,y,w,h;self.calls=[]
    def resize(self,w,h):self.calls.append(("resize",w,h));self.width,self.height=w,h
    def show(self):self.calls.append("show")
    def hide(self):self.calls.append("hide")
@unittest.skipIf(api is None,"pywebview not installed for this interpreter")
class MiniWindowTests(unittest.TestCase):
    def setUp(self):
        self.saved=[];self.destroyed=[]
        self._old=(api._quick_svc._save_mini_settings,api._destroy_soon,dict(api._windows))
        api._quick_svc._save_mini_settings=lambda cfg:self.saved.append(dict(cfg)) or True
        api._destroy_soon=lambda w,delay=0.15:self.destroyed.append(w)
        self.main=_Win();self.win=_Win()
        api._windows.clear();api._windows.update({"main":self.main,"mini":self.win})
        self.m=api.MiniWindowAPI();self.m.bind(self.win,None,(520,420))
    def tearDown(self):
        api._quick_svc._save_mini_settings,api._destroy_soon,w=self._old
        api._windows.clear();api._windows.update(w)
    def test_closing_mini_quits_the_app_instead_of_orphaning_a_hidden_main(self):
        self.m.close()
        self.assertEqual([self.win,self.main],self.destroyed)
        self.assertNotIn("mini",api._windows)
        self.assertEqual({"x":5,"y":6,"w":520,"h":420},self.saved[-1])
    def test_closing_without_quit_shows_main(self):
        self.m.close(False)
        self.assertEqual([self.win],self.destroyed)
        self.assertEqual(["show"],self.main.calls)
    def test_a_move_before_any_resize_keeps_the_real_size(self):
        self.m._on_moved(40,50)
        self.m._on_main_closing()
        self.m._on_closing()
        self.assertEqual({"x":40,"y":50,"w":520,"h":420},self.saved[-1])
    def test_collapse_shrinks_and_remembers_the_expanded_size(self):
        self.m.set_collapsed(True)
        self.assertEqual(("resize",520,api.MINI_COLLAPSED_H),self.win.calls[-1])
        self.assertEqual({"collapsed":True,"w":520,"h":420},self.saved[-1])
        self.m._on_resized(520,api.MINI_COLLAPSED_H)
        self.m.resize_to(600,900)
        self.assertEqual(("resize",600,api.MINI_COLLAPSED_H),self.win.calls[-1])
        self.m.save_geometry()
        self.assertEqual(420,self.saved[-1]["h"])
        self.m.set_collapsed(False)
        self.assertEqual(("resize",600,420),self.win.calls[-1])
        self.assertFalse(self.saved[-1]["collapsed"])
if __name__=="__main__":unittest.main()
