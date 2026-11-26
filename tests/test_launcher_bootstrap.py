import json,os,shutil,subprocess,sys,tempfile,unittest
from _isolate import ROOT
import RunNote
_IS_WINDOWS=sys.platform.startswith("win")
def _system_has_gi():
    try:
        subprocess.run([sys.executable,"-c","import gi"],capture_output=True,timeout=20,check=True)
        return True
    except Exception:
        return False
class VenvCreationFlagTests(unittest.TestCase):
    def setUp(self):
        self.calls=[]
        self._run=RunNote._run
        self._is_win=RunNote._is_win
        self._hide=RunNote._make_hidden_windows
        RunNote._run=lambda cmd,msg=None:(self.calls.append(list(cmd)),(0,""))[1]
        RunNote._make_hidden_windows=lambda p:None
    def tearDown(self):
        RunNote._run=self._run
        RunNote._is_win=self._is_win
        RunNote._make_hidden_windows=self._hide
    def _create(self,is_win):
        RunNote._is_win=lambda:is_win
        target=os.path.join(tempfile.mkdtemp(prefix="loya_venvflag_"),"venv")
        try:
            ok,_=RunNote._ensure_venv(target)
            self.assertTrue(ok)
            return self.calls[-1]
        finally:
            shutil.rmtree(os.path.dirname(target),ignore_errors=True)
    def test_posix_venv_is_created_with_system_site_packages(self):
        self.assertIn("--system-site-packages",self._create(False))
    def test_windows_venv_is_created_without_system_site_packages(self):
        self.assertNotIn("--system-site-packages",self._create(True))
    def test_the_venv_directory_is_still_the_last_argument(self):
        self.assertTrue(self._create(False)[-1].endswith("venv"))
class VenvSiteDetectionTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.mkdtemp(prefix="loya_venvcfg_")
    def tearDown(self):
        shutil.rmtree(self.dir,ignore_errors=True)
    def _write(self,body):
        with open(os.path.join(self.dir,"pyvenv.cfg"),"w",encoding="utf-8") as f:f.write(body)
    def test_true_is_detected(self):
        self._write("home = /usr/bin\ninclude-system-site-packages = true\nversion = 3.13.0\n")
        self.assertTrue(RunNote._venv_sees_system_site(self.dir))
    def test_false_is_detected(self):
        self._write("home = /usr/bin\ninclude-system-site-packages = false\nversion = 3.13.0\n")
        self.assertFalse(RunNote._venv_sees_system_site(self.dir))
    def test_a_missing_config_is_treated_as_no(self):
        self.assertFalse(RunNote._venv_sees_system_site(self.dir))
    def test_capitalised_value_is_accepted(self):
        self._write("include-system-site-packages = True\n")
        self.assertTrue(RunNote._venv_sees_system_site(self.dir))
class VenvPythonChangeTests(unittest.TestCase):
    """A distro upgrade (Kali: Python 3.13 -> 3.14) leaves the venv's python pointing at the new version while its packages
    sit in lib/python3.13, so `import webview` fails. The launcher must notice and rebuild."""
    def setUp(self):
        self.dir=tempfile.mkdtemp(prefix="loya_venvpy_")
    def tearDown(self):
        shutil.rmtree(self.dir,ignore_errors=True)
    def _cfg(self,body):
        with open(os.path.join(self.dir,"pyvenv.cfg"),"w",encoding="utf-8") as f:f.write(body)
    def test_built_for_version_is_read_from_pyvenv_cfg(self):
        self._cfg("home = /usr/bin\ninclude-system-site-packages = true\nversion = 3.13.14\n")
        self.assertEqual("3.13",RunNote._venv_cfg_python(self.dir))
        self._cfg("version_info = 3.12.4.final.0\n")
        self.assertEqual("3.12",RunNote._venv_cfg_python(self.dir))
        os.remove(os.path.join(self.dir,"pyvenv.cfg"))
        self.assertEqual("",RunNote._venv_cfg_python(self.dir))
    def test_the_real_interpreter_version_is_reported(self):
        self.assertEqual("%d.%d"%sys.version_info[:2],RunNote._python_mm(sys.executable))
        self.assertEqual("",RunNote._python_mm(os.path.join(self.dir,"no-such-python")))
    def test_a_changed_python_is_detected(self):
        self._cfg("version = 3.13.14\n")
        orig=RunNote._python_mm
        try:
            RunNote._python_mm=lambda py:"3.14"
            self.assertEqual((True,"3.13","3.14"),RunNote._venv_python_changed(self.dir,"py"))
            RunNote._python_mm=lambda py:"3.13"
            self.assertFalse(RunNote._venv_python_changed(self.dir,"py")[0])
            RunNote._python_mm=lambda py:""   # interpreter does not start: not judged here (the venv check handles it)
            self.assertFalse(RunNote._venv_python_changed(self.dir,"py")[0])
        finally:
            RunNote._python_mm=orig
    def test_deps_state_is_tied_to_the_venv_python(self):
        orig=RunNote._abs
        try:
            RunNote._abs=lambda *p:os.path.join(self.dir,*p)
            reqs=["pywebview==6.2.1"]
            RunNote._save_deps_state(reqs,"3.13")
            self.assertTrue(RunNote._deps_up_to_date(reqs,"3.13"))
            self.assertFalse(RunNote._deps_up_to_date(reqs,"3.14"),"a new Python needs the packages again")
            self.assertFalse(RunNote._deps_up_to_date(["pywebview==7"],"3.13"))
        finally:
            RunNote._abs=orig
    def test_a_missing_critical_import_is_caught(self):
        orig=RunNote._CRITICAL_IMPORTS
        try:
            RunNote._CRITICAL_IMPORTS=("json",)
            self.assertTrue(RunNote._venv_imports_ok(sys.executable))
            RunNote._CRITICAL_IMPORTS=("loya_no_such_module_xyz",)
            self.assertFalse(RunNote._venv_imports_ok(sys.executable))
        finally:
            RunNote._CRITICAL_IMPORTS=orig
class LaunchLivenessTests(unittest.TestCase):
    """The launcher must not say "LOYA NG is running" for an app that died at once (the Python 3.14 upgrade case)."""
    def test_an_app_that_dies_at_once_is_reported(self):
        p=subprocess.Popen([sys.executable,"-c","import sys;sys.exit(3)"])
        self.assertEqual(3,RunNote._app_died_early(p,wait=5))
    def test_a_running_app_is_not_reported(self):
        p=subprocess.Popen([sys.executable,"-c","import time;time.sleep(5)"])
        try:
            self.assertIsNone(RunNote._app_died_early(p,wait=0.5))
        finally:
            p.kill();p.wait()
    def test_no_handle_means_no_verdict(self):
        self.assertIsNone(RunNote._app_died_early(None,wait=0))
    def test_the_last_launch_output_is_shown(self):
        d=tempfile.mkdtemp(prefix="loya_lastout_");orig=RunNote._abs
        try:
            RunNote._abs=lambda *p:os.path.join(d,*p)
            os.makedirs(os.path.join(d,"Logs"))
            with open(os.path.join(d,"Logs","app_output.log"),"w",encoding="utf-8") as f:
                f.write("\n=== 2026-11-26 15:55:06 launch ===\nold error\n\n=== 2026-11-26 15:57:46 launch ===\nTraceback (most recent call last):\nModuleNotFoundError: No module named 'webview'\n")
            out=RunNote._last_launch_output()
            self.assertIn("No module named 'webview'",out);self.assertNotIn("old error",out)
        finally:
            RunNote._abs=orig;shutil.rmtree(d,ignore_errors=True)
class LinuxAppEnvTests(unittest.TestCase):
    KEYS=("WEBKIT_DISABLE_DMABUF_RENDERER","WEBKIT_DMABUF_RENDERER_FORCE_SHM","WEBKIT_SKIA_ENABLE_CPU_RENDERING")
    def setUp(self):
        self.original={k:os.environ.get(k) for k in self.KEYS}
        for k in self.KEYS:os.environ.pop(k,None)
    def tearDown(self):
        for k,v in self.original.items():
            os.environ.pop(k,None)
            if v is not None:os.environ[k]=v
    def test_shared_memory_frames_are_forced_by_default(self):
        env=RunNote._linux_app_env()
        self.assertEqual("1",env.get("WEBKIT_DMABUF_RENDERER_FORCE_SHM"),"WebKitGTK renders a blank white window on virtualised GL drivers without this")
    def test_the_dmabuf_renderer_is_not_disabled(self):
        self.assertNotIn("WEBKIT_DISABLE_DMABUF_RENDERER",RunNote._linux_app_env(),"disabling it turns off compositing, so backdrop-filter glass is never drawn")
    def test_an_explicit_disable_is_honoured_untouched(self):
        os.environ["WEBKIT_DISABLE_DMABUF_RENDERER"]="1"
        env=RunNote._linux_app_env()
        self.assertEqual("1",env.get("WEBKIT_DISABLE_DMABUF_RENDERER"))
        self.assertNotIn("WEBKIT_DMABUF_RENDERER_FORCE_SHM",env)
    def test_an_explicit_shm_setting_is_not_overridden(self):
        os.environ["WEBKIT_DMABUF_RENDERER_FORCE_SHM"]="0"
        self.assertEqual("0",RunNote._linux_app_env().get("WEBKIT_DMABUF_RENDERER_FORCE_SHM"))
    def test_skia_cpu_painting_goes_with_shared_memory_frames(self):
        self.assertEqual("1",RunNote._linux_app_env().get("WEBKIT_SKIA_ENABLE_CPU_RENDERING"),"Skia GPU painting leaves stale glass-card edges on screen with SHM frames")
    def test_skia_cpu_painting_is_left_alone_without_shared_memory_frames(self):
        os.environ["WEBKIT_DMABUF_RENDERER_FORCE_SHM"]="0"
        self.assertNotIn("WEBKIT_SKIA_ENABLE_CPU_RENDERING",RunNote._linux_app_env())
        os.environ.pop("WEBKIT_DMABUF_RENDERER_FORCE_SHM")
        os.environ["WEBKIT_DISABLE_DMABUF_RENDERER"]="1"
        self.assertNotIn("WEBKIT_SKIA_ENABLE_CPU_RENDERING",RunNote._linux_app_env())
    def test_an_explicit_skia_setting_is_not_overridden(self):
        os.environ["WEBKIT_SKIA_ENABLE_CPU_RENDERING"]="0"
        self.assertEqual("0",RunNote._linux_app_env().get("WEBKIT_SKIA_ENABLE_CPU_RENDERING"))
    def test_the_rest_of_the_environment_is_preserved(self):
        os.environ["LOYA_ENV_PROBE"]="kept"
        try:
            self.assertEqual("kept",RunNote._linux_app_env().get("LOYA_ENV_PROBE"))
        finally:
            os.environ.pop("LOYA_ENV_PROBE",None)
class RequirementSpecTests(unittest.TestCase):
    def _specs(self):
        return RunNote._read_requirements(os.path.join(ROOT,"Requirements.json"))[1]
    def test_pywebview_is_requested_without_a_gtk_extra(self):
        pywebview=[s for s in self._specs() if s.lower().startswith("pywebview")]
        self.assertEqual(1,len(pywebview))
        self.assertNotIn("[",pywebview[0],"the gtk extra pins PyGObject==3.50.0 and forces a source build")
    def test_the_pinned_packages_are_still_requested(self):
        joined=" ".join(self._specs()).lower()
        for name in ("cryptography","pywebview","mcp"):
            self.assertIn(name,joined)
@unittest.skipIf(_IS_WINDOWS,"posix only - proves the distro PyGObject is reachable")
@unittest.skipUnless(_system_has_gi(),"no system PyGObject to inherit")
class RealVenvInheritsSystemGiTests(unittest.TestCase):
    def test_a_launcher_created_venv_can_import_gi(self):
        base=tempfile.mkdtemp(prefix="loya_venvreal_")
        target=os.path.join(base,"venv")
        try:
            ok,tail=RunNote._ensure_venv(target)
            self.assertTrue(ok,tail)
            py=os.path.join(target,"bin","python3")
            self.assertTrue(os.path.isfile(py))
            r=subprocess.run([py,"-c","import gi;print(gi.__version__)"],capture_output=True,text=True,timeout=60)
            self.assertEqual(0,r.returncode,f"venv cannot see the distro PyGObject: {r.stderr.strip()}")
            self.assertTrue(r.stdout.strip())
        finally:
            shutil.rmtree(base,ignore_errors=True)
if __name__=="__main__":unittest.main()
