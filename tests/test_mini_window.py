import os,json,sqlite3,tempfile,shutil,threading,time,unittest
from _isolate import ROOT,IsolatedData
from Cores import common_db
from Cores.Services import quick_space_service as qs
try:
    from Cores.Bridge import api
except Exception:
    api=None
class _E:
    def __init__(self):self.items=[]
    def __iadd__(self,f):self.items.append(f);return self
class _Win:
    def __init__(self,x=5,y=6,w=520,h=420):
        class _Ev:pass
        self.events=_Ev()
        for n in ("moved","resized","closing","shown"):setattr(self.events,n,_E())
        self.x,self.y,self.width,self.height=x,y,w,h;self.calls=[];self.js=[]
    def resize(self,w,h):self.calls.append(("resize",w,h))
    def show(self):self.calls.append("show")
    def hide(self):self.calls.append("hide")
    def run_js(self,src):self.js.append(src)
@unittest.skipIf(api is None,"pywebview not installed for this interpreter")
class MiniCloseTests(unittest.TestCase):
    def setUp(self):
        self.saved=[];self.destroyed=[]
        self._old=(qs._save_mini_settings,api._destroy_soon,dict(api._windows))
        api._quick_svc._save_mini_settings=lambda cfg:self.saved.append(dict(cfg)) or True
        api._destroy_soon=lambda w,delay=0.15:self.destroyed.append(w)
        self.main=_Win();self.win=_Win()
        api._windows.clear();api._windows.update({"main":self.main,"mini":self.win})
        self.m=api.MiniWindowAPI();self.m.bind(self.win,(5,6,520,420),(520,420))
    def tearDown(self):
        api._quick_svc._save_mini_settings,api._destroy_soon,w=self._old
        api._windows.clear();api._windows.update(w)
    def _wait(self,cond,t=2.0):
        end=time.time()+t
        while time.time()<end and not cond():time.sleep(0.01)
        return cond()
    def test_alt_f4_is_cancelled_and_quits_through_the_page_so_quick_space_is_saved(self):
        # A WM close used to destroy only Mini, leaving the hidden main window as an invisible orphan process.
        self.assertIs(False,self.m._on_closing())
        self.assertIn("mini",api._windows)
        self.assertTrue(self._wait(lambda:self.win.js),"the page is asked to save and quit")
        self.assertIn("miniCloseApp()",self.win.js[0])
        self.assertEqual([],self.destroyed)
    def test_a_second_wm_close_does_not_start_a_second_quit(self):
        self.m._on_closing();self.m._on_closing()
        time.sleep(0.1)
        self.assertEqual(1,len(self.win.js))
    def test_wm_close_falls_back_to_quitting_when_the_page_never_answers(self):
        self.m._quit_from_wm(grace=0.05)
        self.assertTrue(self._wait(lambda:len(self.destroyed)==2))
        self.assertEqual([self.win,self.main],self.destroyed)
    def test_the_x_button_path_is_allowed_through(self):
        self.m.close(True)
        self.assertIsNone(self.m._on_closing())
        self.assertNotIn("mini",api._windows)
    def test_closing_the_main_window_lets_mini_close(self):
        self.assertEqual(1,len(self.main.events.closing.items),"Mini listens for the main window closing")
        self.main.events.closing.items[0]()
        self.assertIsNone(self.m._on_closing())
        self.assertEqual([{"x":5,"y":6,"w":520,"h":420}],self.saved)
    def test_activity_resets_the_main_idle_timer_and_is_throttled(self):
        self.assertTrue(self.m.activity())
        self.assertTrue(self.m.activity())
        self.assertEqual(1,len(self.main.js))
        self.assertIn("idleResetActivity()",self.main.js[0])
    def test_open_related_note_script_returns_a_plain_value(self):
        # A bare promise result made WebKitGTK log "Unsupported result type".
        self.assertTrue(self.m.restore_and_open_note(7))
        self.assertTrue(self.main.js[-1].endswith(";0"))
        self.assertIn("notesOpen(7)",self.main.js[-1])
class MiniSettingsFileTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.mkdtemp(prefix="loya_mini_")
        self._paths=(qs._settings_path,qs._quick_space_path)
        qs._settings_path=lambda:os.path.join(self.dir,"settings.json")
        qs._quick_space_path=lambda:os.path.join(self.dir,"QuicSpace.json")
    def tearDown(self):
        qs._settings_path,qs._quick_space_path=self._paths
        shutil.rmtree(self.dir,ignore_errors=True)
    def test_mini_settings_merge_into_settings_json_and_keep_other_keys(self):
        with open(qs._settings_path(),"w",encoding="utf-8") as f:json.dump({"window":{"w":900},"mini_window":{"x":1}},f)
        self.assertTrue(qs._save_mini_settings({"collapsed":True}))
        d=json.load(open(qs._settings_path(),encoding="utf-8"))
        self.assertEqual({"w":900},d["window"])
        self.assertEqual({"x":1,"collapsed":True},d["mini_window"])
    def test_concurrent_mini_and_main_writes_do_not_drop_keys(self):
        from Cores import settings_lock
        def mini(i):qs._save_mini_settings({f"k{i}":i})
        def main(i):settings_lock.update_json(qs._settings_path(),lambda d:d.__setitem__(f"main{i}",i))
        ts=[threading.Thread(target=(mini if i%2 else main),args=(i,)) for i in range(40)]
        for t in ts:t.start()
        for t in ts:t.join()
        d=json.load(open(qs._settings_path(),encoding="utf-8"))
        self.assertEqual(20,len(d["mini_window"]))
        self.assertEqual(20,len([k for k in d if k.startswith("main")]))
    def test_parallel_quick_space_saves_never_fail(self):
        res=[]
        def save(i):res.append(qs._write_json(qs._quick_space_path(),{"html":"x"*i,"text":"","wrap":True}))
        ts=[threading.Thread(target=save,args=(i,)) for i in range(30)]
        for t in ts:t.start()
        for t in ts:t.join()
        self.assertTrue(all(res))
        self.assertEqual(set(),{n for n in os.listdir(self.dir) if n.endswith(".tmp")})
class SchemaMtimeTests(unittest.TestCase):
    def setUp(self):self.iso=IsolatedData();self.iso.start()
    def tearDown(self):self.iso.stop()
    def test_ensure_schema_does_not_rewrite_an_up_to_date_database(self):
        # Mini and the targets cache reload whenever the DB mtime changes; PRAGMA user_version=N rewrote it on every read.
        with sqlite3.connect(common_db.db_path()) as con:common_db.ensure_schema(con)
        p=common_db.db_path()
        st=os.stat(p).st_mtime_ns;os.utime(p,ns=(st-10**9,st-10**9));before=os.stat(p).st_mtime_ns
        con=sqlite3.connect(p);common_db.ensure_schema(con);con.close()
        self.assertEqual(before,os.stat(p).st_mtime_ns)
        con=sqlite3.connect(p);self.assertEqual(common_db.DB_SCHEMA_VERSION,con.execute("PRAGMA user_version").fetchone()[0]);con.close()
if __name__=="__main__":unittest.main()
