import os,re,shutil,stat,sys,tempfile,threading,time,unittest
from _isolate import ROOT
try:
    from Cores.Bridge import api
except Exception:
    api=None
try:
    from webview.util import parse_file_type
except Exception:
    parse_file_type=None
try:
    from gi.repository import GLib
except Exception:
    GLib=None
from Cores.Update import recovery
_IS_LINUX=sys.platform.startswith("linux")
_HAS_DISPLAY=bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
class _Platform:
    def __init__(self,linux):self.linux=linux
    def __enter__(self):
        self._old=api._IS_LINUX;api._IS_LINUX=self.linux;return self
    def __exit__(self,*a):api._IS_LINUX=self._old
class _Settings:
    def __init__(self,initial=None):self.data=dict(initial or {});self.writes=0
    def __enter__(self):
        self._r,self._w=api.read_settings,api.write_settings
        api.read_settings=lambda:dict(self.data)
        def write(d):self.writes+=1;self.data=dict(d)
        api.write_settings=write
        return self
    def __exit__(self,*a):api.read_settings,api.write_settings=self._r,self._w
class _DialogWindow:
    def __init__(self,answers,confirm=True):
        self.answers=list(answers);self.calls=[];self.confirms=[];self.confirm=confirm
    def create_file_dialog(self,dialog_type,directory="",allow_multiple=False,save_filename="",file_types=()):
        self.calls.append({"type":dialog_type,"directory":directory,"save_filename":save_filename,"file_types":file_types})
        return self.answers.pop(0) if self.answers else None
    def create_confirmation_dialog(self,title,message):
        self.confirms.append(message);return self.confirm
@unittest.skipIf(api is None,"pywebview not installed for this interpreter")
class SaveExtensionTests(unittest.TestCase):
    def test_a_missing_extension_is_appended(self):
        self.assertEqual(os.path.join("/tmp","report.md"),api._with_extension("/tmp/report","md"))
    def test_an_existing_extension_is_kept_whatever_its_case(self):
        self.assertEqual("/tmp/report.md",api._with_extension("/tmp/report.md","md"))
        self.assertEqual("/tmp/REPORT.MD",api._with_extension("/tmp/REPORT.MD","md"))
    def test_a_different_extension_gets_the_expected_one_too(self):
        self.assertEqual(os.path.join("/tmp","notes.txt.json"),api._with_extension("/tmp/notes.txt","json"))
    def test_a_trailing_dot_is_not_doubled(self):
        self.assertEqual(os.path.join("/tmp","report.md"),api._with_extension("/tmp/report.","md"))
    def test_nothing_to_append_leaves_the_path_alone(self):
        self.assertEqual("/tmp/x",api._with_extension("/tmp/x",""))
        self.assertIsNone(api._with_extension(None,"md"))
@unittest.skipIf(api is None,"pywebview not installed for this interpreter")
class FileFilterTests(unittest.TestCase):
    def test_linux_filters_match_both_cases(self):
        with _Platform(True):
            self.assertEqual("JSON (*.json;*.JSON)",api._file_types("JSON","json"))
            self.assertEqual("CherryTree (*.ctd;*.CTD)",api._file_types("CherryTree","ctd"))
            self.assertEqual("Markdown ZIP (*.zip;*.ZIP)",api._file_types("Markdown ZIP","zip"))
    def test_windows_filters_are_unchanged(self):
        with _Platform(False):
            self.assertEqual("JSON (*.json)",api._file_types("JSON","json"))
            self.assertEqual("Word Document (*.docx)",api._file_types("Word Document","docx"))
    @unittest.skipIf(parse_file_type is None,"pywebview not installed")
    def test_every_filter_the_app_uses_passes_pywebview_validation(self):
        labels=[("Markdown","md"),("HTML","html"),("PDF","pdf"),("Word Document","docx"),("JSON","json"),("CSV","csv"),("Markdown ZIP","zip"),("PNG","png"),("CherryTree","ctd"),("ZIP","zip"),("Text","txt")]
        for linux in (True,False):
            with _Platform(linux):
                for label,ext in labels:
                    desc,pats=parse_file_type(api._file_types(label,ext))
                    self.assertEqual(label,desc)
                    self.assertIn(f"*.{ext}",pats.split(";"))
@unittest.skipIf(api is None,"pywebview not installed for this interpreter")
class DialogDirectoryTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.mkdtemp(prefix="loya_dlg_")
    def tearDown(self):shutil.rmtree(self.tmp,ignore_errors=True)
    def test_windows_keeps_the_os_default_directory(self):
        with _Platform(False),_Settings({"last_dialog_dir":self.tmp}) as s:
            self.assertEqual("",api._dialog_dir())
            api._remember_dialog_dir(self.tmp)
            self.assertEqual(0,s.writes)
    def test_the_last_used_folder_is_reused(self):
        with _Platform(True),_Settings({"last_dialog_dir":self.tmp}):
            self.assertEqual(self.tmp,api._dialog_dir())
    def test_a_vanished_folder_falls_back_to_documents_or_home(self):
        gone=os.path.join(self.tmp,"gone")
        with _Platform(True),_Settings({"last_dialog_dir":gone}):
            d=api._dialog_dir()
            self.assertTrue(os.path.isdir(d))
            self.assertEqual(api._default_dialog_dir(),d)
    def test_remembering_persists_and_skips_redundant_writes(self):
        with _Platform(True),_Settings({"other":1}) as s:
            api._remember_dialog_dir(self.tmp)
            self.assertEqual({"other":1,"last_dialog_dir":os.path.abspath(self.tmp)},s.data)
            api._remember_dialog_dir(self.tmp)
            self.assertEqual(1,s.writes)
            api._remember_dialog_dir(os.path.join(self.tmp,"missing"))
            self.assertEqual(1,s.writes)
    def test_every_dialog_opens_in_the_remembered_folder_and_updates_it(self):
        sub=os.path.join(self.tmp,"sub");os.makedirs(sub)
        with _Platform(True),_Settings({"last_dialog_dir":self.tmp}) as s:
            w=_DialogWindow([(os.path.join(sub,"a.json"),)])
            self.assertEqual((os.path.join(sub,"a.json"),),api._open_dialog(w,"JSON","json"))
            self.assertEqual(self.tmp,w.calls[0]["directory"])
            self.assertEqual(("JSON (*.json;*.JSON)",),w.calls[0]["file_types"])
            self.assertEqual(sub,s.data["last_dialog_dir"])
            w=_DialogWindow([(self.tmp,)])
            self.assertEqual(self.tmp,api._folder_dialog(w))
            self.assertEqual(sub,w.calls[0]["directory"])
            self.assertEqual(self.tmp,s.data["last_dialog_dir"])
@unittest.skipIf(api is None,"pywebview not installed for this interpreter")
class SaveDialogTests(unittest.TestCase):
    def setUp(self):self.tmp=tempfile.mkdtemp(prefix="loya_save_")
    def tearDown(self):shutil.rmtree(self.tmp,ignore_errors=True)
    def test_cancel_returns_none(self):
        with _Platform(True),_Settings():
            self.assertIsNone(api._save_dialog(_DialogWindow([None]),"JSON","json","x.json"))
    def test_linux_appends_the_extension_gtk_left_off(self):
        with _Platform(True),_Settings() as s:
            w=_DialogWindow([(os.path.join(self.tmp,"notes"),)])
            self.assertEqual(os.path.join(self.tmp,"notes.json"),api._save_dialog(w,"JSON","json","notes.json"))
            self.assertEqual([],w.confirms)
            self.assertEqual("notes.json",w.calls[0]["save_filename"])
            self.assertEqual(self.tmp,s.data["last_dialog_dir"])
    def test_a_name_gtk_already_confirmed_is_kept_as_is(self):
        target=os.path.join(self.tmp,"notes.json");open(target,"w").close()
        with _Platform(True),_Settings():
            w=_DialogWindow([(target,)])
            self.assertEqual(target,api._save_dialog(w,"JSON","json","notes.json"))
            self.assertEqual([],w.confirms,"GTK already asked about this exact name")
    def test_appending_onto_an_existing_file_asks_first(self):
        open(os.path.join(self.tmp,"notes.json"),"w").close()
        with _Platform(True),_Settings():
            w=_DialogWindow([(os.path.join(self.tmp,"notes"),)],confirm=True)
            self.assertEqual(os.path.join(self.tmp,"notes.json"),api._save_dialog(w,"JSON","json","x.json"))
            self.assertEqual(1,len(w.confirms))
            self.assertIn("notes.json",w.confirms[0])
    def test_declining_the_replace_reopens_the_dialog_on_that_name(self):
        open(os.path.join(self.tmp,"notes.json"),"w").close()
        with _Platform(True),_Settings():
            w=_DialogWindow([(os.path.join(self.tmp,"notes"),),(os.path.join(self.tmp,"notes2.json"),)],confirm=False)
            self.assertEqual(os.path.join(self.tmp,"notes2.json"),api._save_dialog(w,"JSON","json","x.json"))
            self.assertEqual(2,len(w.calls))
            self.assertEqual((self.tmp,"notes.json"),(w.calls[1]["directory"],w.calls[1]["save_filename"]))
    def test_windows_returns_exactly_what_the_dialog_gave(self):
        with _Platform(False),_Settings() as s:
            w=_DialogWindow([(os.path.join(self.tmp,"notes"),)])
            self.assertEqual(os.path.join(self.tmp,"notes"),api._save_dialog(w,"JSON","json","notes.json"))
            self.assertEqual({"type":api.webview.FileDialog.SAVE,"directory":"","save_filename":"notes.json","file_types":("JSON (*.json)",)},w.calls[0])
            self.assertEqual(0,s.writes)
class _Events:
    def __init__(self):
        class _E:
            def __iadd__(self,f):return self
        for n in ("maximized","restored","moved","resized","closing","shown"):setattr(self,n,_E())
class _ExplodingWindow:
    uid="test"
    def __init__(self):self.events=_Events();self.calls=[]
    def __getattr__(self,name):
        if name in ("x","y","width","height"):raise AssertionError("reading window geometry inside closing deadlocks the GTK main loop")
        raise AttributeError(name)
    def restore(self):self.calls.append("restore")
    def resize(self,w,h):self.calls.append(("resize",w,h))
    def move(self,x,y):self.calls.append(("move",x,y))
@unittest.skipIf(api is None,"pywebview not installed for this interpreter")
class MiniGeometryTests(unittest.TestCase):
    def setUp(self):
        self.saved=[]
        self._save=api._quick_svc._save_mini_settings
        api._quick_svc._save_mini_settings=lambda cfg:self.saved.append(dict(cfg)) or True
    def tearDown(self):api._quick_svc._save_mini_settings=self._save
    def test_known_position_seeds_the_cache(self):
        with _Platform(True):self.assertEqual((10,20,520,420),api._mini_seed_geometry(10,20,520,420,[]))
    def test_a_centred_window_is_seeded_where_gtk_centres_it(self):
        class _S:x=0;y=0;width=1920;height=1080
        with _Platform(True):self.assertEqual((700,330,520,420),api._mini_seed_geometry(None,None,520,420,[_S()]))
    def test_windows_does_not_seed(self):
        with _Platform(False):self.assertIsNone(api._mini_seed_geometry(10,20,520,420,[]))
    def test_closing_a_seeded_mini_saves_without_touching_the_window(self):
        with _Platform(True):
            m=api.MiniWindowAPI();m.bind(_ExplodingWindow(),(10,20,520,420))
            m._on_closing()
        self.assertEqual([{"x":10,"y":20,"w":520,"h":420}],self.saved)
    def test_closing_an_unseeded_mini_on_linux_skips_the_save_instead_of_deadlocking(self):
        with _Platform(True):
            m=api.MiniWindowAPI();m.bind(_ExplodingWindow())
            m._on_closing()
        self.assertEqual([],self.saved)
class _Stub:
    def __getattr__(self,name):return lambda *a,**k:(True,"")
@unittest.skipIf(api is None,"pywebview not installed for this interpreter")
class MainWindowLinuxTests(unittest.TestCase):
    def setUp(self):
        self._svc=(api._terminal_svc,api._mcp_local_svc,api._security_svc,api._destroy_soon,api._gtk_unmaximize)
        api._terminal_svc=api._mcp_local_svc=api._security_svc=_Stub()
        self.destroyed=[];self.unmax=[]
        api._destroy_soon=lambda w,delay=0.15:self.destroyed.append(w)
        api._gtk_unmaximize=lambda w:self.unmax.append(w) or True
        self.window=_ExplodingWindow()
        self.api=api.WindowAPI();self.api.bind(self.window,False,(10,20,800,600))
        self._mini=api._windows.get("mini")
    def tearDown(self):
        api._terminal_svc,api._mcp_local_svc,api._security_svc,api._destroy_soon,api._gtk_unmaximize=self._svc
        if self._mini is None:api._windows.pop("mini",None)
        else:api._windows["mini"]=self._mini
    def test_closing_the_main_window_destroys_a_hidden_mini_on_linux(self):
        mini=object();api._windows["mini"]=mini
        with _Platform(True),_Settings():self.api._on_closing()
        self.assertEqual([mini],self.destroyed)
    def test_closing_on_windows_leaves_the_mini_alone(self):
        api._windows["mini"]=object()
        with _Platform(False),_Settings():self.api._on_closing()
        self.assertEqual([],self.destroyed)
    def test_a_window_manager_maximize_drops_the_stale_restore_size(self):
        self.api._pre_maximize_geo=(1,2,300,400)
        with _Platform(True):self.api._on_maximized()
        self.assertTrue(self.api._maximized)
        self.assertIsNone(self.api._pre_maximize_geo,"the WM keeps its own restore size; ours is from an older maximize")
    def test_a_wm_maximize_on_top_of_ours_keeps_the_real_restore_size(self):
        self.api._maximized=True;self.api._pre_maximize_geo=(1,2,300,400)
        with _Platform(True):self.api._on_maximized()
        self.assertEqual((1,2,300,400),self.api._pre_maximize_geo)
    def test_restoring_unmaximizes_natively_before_resizing(self):
        self.api._maximized=True;self.api._pre_maximize_geo=(1,2,300,400)
        self.assertFalse(self.api.toggle_maximize())
        self.assertEqual([self.window],self.unmax)
        self.assertEqual(["restore",("resize",300,400),("move",1,2)],self.window.calls)
    def test_restore_for_drag_unmaximizes_too(self):
        self.api._maximized=True;self.api._pre_maximize_geo=(1,2,300,400)
        self.api.restore_for_drag(500,10,0.5)
        self.assertEqual([self.window],self.unmax)
@unittest.skipIf(api is None,"pywebview not installed for this interpreter")
class GtkMainLoopTests(unittest.TestCase):
    def test_unmaximize_is_a_no_op_off_linux(self):
        with _Platform(False):self.assertFalse(api._gtk_unmaximize(_ExplodingWindow()))
    def test_the_main_thread_runs_inline(self):
        self.assertEqual(threading.main_thread(),api._run_on_gtk_main(threading.current_thread))
    @unittest.skipIf(GLib is None,"PyGObject not installed")
    def test_a_worker_thread_is_marshalled_onto_the_main_loop(self):
        loop=GLib.MainLoop();out={}
        def worker():
            out["thread"]=api._run_on_gtk_main(threading.current_thread,timeout=5)
            GLib.idle_add(loop.quit)
        threading.Thread(target=worker,daemon=True).start()
        GLib.timeout_add(5000,loop.quit)
        loop.run()
        self.assertIs(threading.main_thread(),out.get("thread"))
    @unittest.skipIf(GLib is None,"PyGObject not installed")
    def test_a_stalled_main_loop_times_out_instead_of_hanging(self):
        out={}
        def worker():out["v"]=api._run_on_gtk_main(lambda:"late",timeout=0.2)
        t=threading.Thread(target=worker,daemon=True);t.start();t.join(3)
        self.assertFalse(t.is_alive())
        self.assertIsNone(out.get("v","missing"))
        ctx=GLib.MainContext.default()
        while ctx.pending():ctx.iteration(False)
@unittest.skipIf(api is None,"pywebview not installed for this interpreter")
class WindowBackgroundTests(unittest.TestCase):
    def setUp(self):self._theme=api._tokens.current_theme
    def tearDown(self):api._tokens.current_theme=self._theme
    def test_the_active_theme_background_is_used(self):
        for theme in ("dark","light","royal"):
            api._tokens.current_theme=lambda t=theme:t
            self.assertEqual(api._tokens.GLASS[theme]["bg"],api._window_background())
            self.assertRegex(api._window_background(),r"^#(?:[0-9a-fA-F]{3}){1,2}$")
    def test_an_unknown_theme_falls_back_to_dark(self):
        api._tokens.current_theme=lambda:"nope"
        self.assertEqual(api._tokens.GLASS["dark"]["bg"],api._window_background())
    def test_windows_passes_nothing(self):
        with _Platform(False):self.assertEqual({},api._window_color_kwargs())
        with _Platform(True):self.assertIn("background_color",api._window_color_kwargs())
@unittest.skipIf(sys.platform.startswith("win"),"xdg-open is the POSIX path")
class OpenWithDesktopTests(unittest.TestCase):
    def setUp(self):
        self.bin=tempfile.mkdtemp(prefix="loya_xdg_")
        self._path=os.environ.get("PATH","")
        os.environ["PATH"]=self.bin+os.pathsep+self._path
    def tearDown(self):
        os.environ["PATH"]=self._path
        shutil.rmtree(self.bin,ignore_errors=True)
    def _opener(self,body):
        name="open" if sys.platform=="darwin" else "xdg-open"
        p=os.path.join(self.bin,name)
        with open(p,"w") as f:f.write("#!/bin/sh\n"+body+"\n")
        os.chmod(p,os.stat(p).st_mode|stat.S_IEXEC)
    def test_success(self):
        self._opener("exit 0")
        self.assertEqual((True,""),recovery.open_with_desktop("/tmp"))
    def test_a_failing_opener_is_reported_with_its_message(self):
        self._opener("echo 'no method available for opening' >&2; exit 3")
        ok,msg=recovery.open_with_desktop("/tmp/x")
        self.assertFalse(ok)
        self.assertIn("no method available",msg)
    def test_a_silent_failure_still_explains_itself(self):
        self._opener("exit 4")
        ok,msg=recovery.open_with_desktop("/tmp/x")
        self.assertFalse(ok)
        self.assertIn("code 4",msg)
    def test_a_long_running_opener_counts_as_success_and_is_not_killed(self):
        marker=os.path.join(self.bin,"done")
        self._opener(f"sleep 0.6; touch '{marker}'")
        t=time.time()
        self.assertEqual((True,""),recovery.open_with_desktop("/tmp",timeout=0.2))
        self.assertLess(time.time()-t,0.5)
        for _ in range(30):
            if os.path.exists(marker):break
            time.sleep(0.1)
        self.assertTrue(os.path.exists(marker),"the opener was killed instead of being left to finish")
    def test_a_missing_opener_is_reported(self):
        os.environ["PATH"]=self.bin
        ok,msg=recovery.open_with_desktop("/tmp")
        self.assertFalse(ok)
        self.assertIn("not installed",msg)
@unittest.skipIf(api is None,"pywebview not installed for this interpreter")
@unittest.skipUnless(_IS_LINUX,"the open-folder bridge only shells out on POSIX")
class OpenPathBridgeTests(unittest.TestCase):
    def setUp(self):self._o=api._recovery.open_with_desktop
    def tearDown(self):api._recovery.open_with_desktop=self._o
    def test_a_failure_reaches_the_ui_as_an_error(self):
        api._recovery.open_with_desktop=lambda p:(False,"no handler")
        with self.assertRaisesRegex(ValueError,"Open failed: no handler"):api.UpdateAPI()._open_path("/tmp")
    def test_success_returns_true(self):
        api._recovery.open_with_desktop=lambda p:(True,"")
        self.assertTrue(api.UpdateAPI()._open_path("/tmp"))
@unittest.skipUnless(_IS_LINUX and _HAS_DISPLAY,"needs GTK and a display (no window is shown)")
class GtkOverwriteHookTests(unittest.TestCase):
    def setUp(self):
        try:
            import gi;gi.require_version("Gtk","3.0")
            from gi.repository import Gtk
            from webview.platforms.gtk import BrowserView
            import LOYA_Note
        except Exception as e:
            self.skipTest(f"GTK backend unavailable ({e})")
        self.Gtk,self.BrowserView,self.launcher=Gtk,BrowserView,LOYA_Note
        self._orig=BrowserView.__dict__["_add_file_filters"]
    def tearDown(self):self.BrowserView._add_file_filters=self._orig
    def _dialog(self,action):return self.Gtk.FileChooserDialog(title="t",action=action)
    def test_save_dialogs_confirm_overwrites_and_others_are_untouched(self):
        self.assertEqual("installed",self.launcher._enable_gtk_overwrite_confirmation())
        self.assertEqual("already installed",self.launcher._enable_gtk_overwrite_confirmation())
        save=self._dialog(self.Gtk.FileChooserAction.SAVE)
        self.BrowserView._add_file_filters(None,save,("JSON (*.json;*.JSON)",))
        self.assertTrue(save.get_do_overwrite_confirmation())
        self.assertEqual(1,len(save.list_filters()))
        opened=self._dialog(self.Gtk.FileChooserAction.OPEN)
        self.BrowserView._add_file_filters(None,opened,())
        self.assertFalse(opened.get_do_overwrite_confirmation())
        save.destroy();opened.destroy()
if __name__=="__main__":unittest.main()
