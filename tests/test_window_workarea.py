import os,shutil,subprocess,sys,time,unittest
from _isolate import ROOT
try:
    from Cores.Bridge import api
except Exception:
    api=None
_IS_LINUX=sys.platform.startswith("linux")
def _has_x_workarea():
    if not _IS_LINUX or not os.environ.get("DISPLAY") or not shutil.which("xprop"):return False
    try:
        return "_NET_WORKAREA" in subprocess.check_output(["xprop","-root","_NET_WORKAREA"],stderr=subprocess.DEVNULL,text=True,timeout=5)
    except Exception:
        return False
def _x_workarea():
    out=subprocess.check_output(["xprop","-root","_NET_WORKAREA"],stderr=subprocess.DEVNULL,text=True,timeout=5)
    nums=[int(v) for v in out.split("=")[-1].replace(","," ").split() if v.lstrip("-").isdigit()]
    return tuple(nums[:4])
class _Rect:
    def __init__(self,x,y,w,h):self.x=x;self.y=y;self.width=w;self.height=h
class _Screen:
    def __init__(self,x,y,w,h,frame):self.x=x;self.y=y;self.width=w;self.height=h;self.frame=frame
class _Window:
    x=100;y=100;width=800;height=600
@unittest.skipIf(api is None,"pywebview not installed for this interpreter")
class WorkAreaPrecedenceTests(unittest.TestCase):
    def setUp(self):
        self._screen_for_window=api._screen_for_window
        self._linux_work_area=api._linux_work_area
        self.screen=_Screen(0,0,1920,1080,_Rect(0,0,1920,1080))
        api._screen_for_window=lambda window:self.screen
    def tearDown(self):
        api._screen_for_window=self._screen_for_window
        api._linux_work_area=self._linux_work_area
    def test_the_platform_work_area_wins_over_the_full_monitor_frame(self):
        api._linux_work_area=lambda scr:(0,35,1920,1045)
        self.assertEqual((0,35,1920,1045),api._work_area_for_window(_Window()),"GTK reports the full monitor geometry as frame, so a panel would be ignored")
    def test_the_frame_is_used_when_no_platform_work_area_is_available(self):
        api._linux_work_area=lambda scr:None
        self.assertEqual((0,0,1920,1080),api._work_area_for_window(_Window()))
    def test_a_side_panel_is_respected_too(self):
        api._linux_work_area=lambda scr:(60,0,1860,1080)
        self.assertEqual((60,0,1860,1080),api._work_area_for_window(_Window()))
    def test_the_result_is_never_smaller_than_the_minimum_window(self):
        api._linux_work_area=lambda scr:(0,0,10,10)
        x,y,w,h=api._work_area_for_window(_Window())
        self.assertGreaterEqual(w,api.MIN_W)
        self.assertGreaterEqual(h,api.MIN_H)
class _ExplodingWindow:
    @property
    def x(self):raise AssertionError("reading window.x inside the closing handler deadlocks the GTK main loop")
    @property
    def y(self):raise AssertionError("reading window.y inside the closing handler deadlocks the GTK main loop")
    @property
    def width(self):raise AssertionError("reading window.width inside the closing handler deadlocks the GTK main loop")
    @property
    def height(self):raise AssertionError("reading window.height inside the closing handler deadlocks the GTK main loop")
@unittest.skipIf(api is None,"pywebview not installed for this interpreter")
class WindowGeometryCacheTests(unittest.TestCase):
    def setUp(self):
        self.written={}
        self._read=api.read_settings
        self._write=api.write_settings
        api.read_settings=lambda:{}
        api.write_settings=lambda d:self.written.update(d)
        self.window=api.WindowAPI()
        self.window._geo=(10,20,800,600)
    def tearDown(self):
        api.read_settings=self._read
        api.write_settings=self._write
    def test_moving_updates_the_position_and_keeps_the_size(self):
        self.window._on_moved(300,150)
        self.assertEqual((300,150,800,600),self.window._geo)
    def test_resizing_updates_the_size_and_keeps_the_position(self):
        self.window._on_resized(1024,768)
        self.assertEqual((10,20,1024,768),self.window._geo)
    def test_saving_prefers_the_cached_geometry_over_reading_the_window(self):
        api.save_window_geometry(_ExplodingWindow(),False,None,(11,22,900,700))
        self.assertEqual({"x":11,"y":22,"w":900,"h":700,"maximized":False},self.written["window"])
    def test_a_maximized_window_still_saves_its_restored_size(self):
        api.save_window_geometry(_ExplodingWindow(),True,(5,6,700,500),(0,35,1920,1045))
        self.assertEqual({"x":5,"y":6,"w":700,"h":500,"maximized":True},self.written["window"])
@unittest.skipIf(api is None,"pywebview not installed for this interpreter")
class WindowDestroyTests(unittest.TestCase):
    def test_close_defers_the_destroy_so_the_bridge_call_can_return(self):
        calls=[]
        class _W:
            def destroy(self_inner):calls.append("destroyed")
        window=_W()
        api._destroy_soon(window,0.05)
        self.assertEqual([],calls,"destroying inline strands the bridge reply and hangs interpreter shutdown")
        time.sleep(0.3)
        self.assertEqual(["destroyed"],calls)
@unittest.skipIf(api is None,"pywebview not installed for this interpreter")
@unittest.skipUnless(_has_x_workarea(),"needs a real X session exposing _NET_WORKAREA")
class WorkAreaOnThisDesktopTests(unittest.TestCase):
    def test_the_work_area_matches_the_window_manager(self):
        import webview
        screens=webview.screens
        self.assertTrue(screens)
        self.assertEqual(_x_workarea(),api._linux_work_area(screens[0]))
    def test_maximizing_stays_inside_the_screen(self):
        import webview
        screens=webview.screens
        x,y,w,h=api._work_area_for_window(_Window())
        self.assertLessEqual(y+h,screens[0].y+screens[0].height,"the maximized window would hang off the bottom of the screen")
        self.assertLessEqual(x+w,screens[0].x+screens[0].width)
if __name__=="__main__":unittest.main()
