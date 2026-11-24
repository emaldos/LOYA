import logging,os,shutil,subprocess,sys,tempfile,threading,unittest
from _isolate import ROOT
import LOYA_Note
class CrashLoggingTests(unittest.TestCase):
    def setUp(self):
        self.dir=tempfile.mkdtemp(prefix="loya_crashlog_")
        self._abs=LOYA_Note._abs;self._log=LOYA_Note._LOG
        self._sys_hook=sys.excepthook;self._thread_hook=threading.excepthook
        LOYA_Note._abs=lambda *p:os.path.join(self.dir,*p)
        lg=logging.getLogger("loya_crashlog_test");lg.handlers.clear();lg.setLevel(logging.INFO);lg.propagate=False
        self.logfile=os.path.join(self.dir,"note.log")
        lg.addHandler(logging.FileHandler(self.logfile,encoding="utf-8"))
        LOYA_Note._LOG=lg
    def tearDown(self):
        import faulthandler
        faulthandler.disable()
        if LOYA_Note._CRASH_FH:
            try:LOYA_Note._CRASH_FH.close()
            except Exception:pass
            LOYA_Note._CRASH_FH=None
        for h in list(LOYA_Note._LOG.handlers):h.close();LOYA_Note._LOG.removeHandler(h)
        LOYA_Note._abs=self._abs;LOYA_Note._LOG=self._log
        sys.excepthook=self._sys_hook;threading.excepthook=self._thread_hook
        shutil.rmtree(self.dir,ignore_errors=True)
    def _note_log(self):
        for h in LOYA_Note._LOG.handlers:h.flush()
        with open(self.logfile,encoding="utf-8") as f:return f.read()
    def test_a_thread_error_is_written_to_the_note_log(self):
        LOYA_Note._install_crash_logging()
        def boom():raise RuntimeError("thread went wrong")
        t=threading.Thread(target=boom,name="worker-x");t.start();t.join()
        text=self._note_log()
        self.assertIn("Uncaught error in thread worker-x",text)
        self.assertIn("RuntimeError: thread went wrong",text)
    def test_crash_log_gets_a_session_header(self):
        LOYA_Note._install_crash_logging()
        with open(os.path.join(self.dir,"Logs","crash.log"),encoding="utf-8") as f:text=f.read()
        self.assertIn(f"PID {os.getpid()} started",text)
    def test_an_oversized_crash_log_is_started_fresh(self):
        os.makedirs(os.path.join(self.dir,"Logs"))
        path=os.path.join(self.dir,"Logs","crash.log")
        with open(path,"w",encoding="utf-8") as f:f.write("x"*(LOYA_Note.CRASH_LOG_MAX+10))
        LOYA_Note._install_crash_logging()
        self.assertLess(os.path.getsize(path),1000)
    def test_main_installs_crash_logging_first(self):
        import inspect
        body=inspect.getsource(LOYA_Note.main).splitlines()
        self.assertEqual("_install_crash_logging()",body[1].strip())
    @unittest.skipIf(sys.platform.startswith("win"),"native crash simulation is POSIX only here")
    def test_a_native_crash_leaves_a_python_stack_in_crash_log(self):
        code=("import sys,os;sys.path.insert(0,sys.argv[1]);sys.path.insert(0,os.path.join(sys.argv[1],'tests'));"
              "import _isolate,LOYA_Note;LOYA_Note._abs=lambda *p:os.path.join(sys.argv[2],*p);"
              "LOYA_Note._install_crash_logging();import faulthandler;faulthandler._sigsegv()")
        r=subprocess.run([sys.executable,"-c",code,ROOT,self.dir],capture_output=True,text=True,timeout=120)
        self.assertNotEqual(0,r.returncode)
        with open(os.path.join(self.dir,"Logs","crash.log"),encoding="utf-8") as f:text=f.read()
        self.assertIn("Fatal Python error",text)
        self.assertIn("Segmentation fault",text)
class LauncherOutputLogTests(unittest.TestCase):
    def setUp(self):
        import RunNote
        self.R=RunNote;self.dir=tempfile.mkdtemp(prefix="loya_applog_")
        self._abs=RunNote._abs;self._spawn=RunNote._spawn_app
        RunNote._abs=lambda *p:os.path.join(self.dir,*p)
        self.seen={}
        def spawn(py,pyw,app_path,stdin,stdout,stderr):
            self.seen.update(stdout=stdout,stderr=stderr,closed_during=getattr(stdout,"closed",None))
            return True,"",123
        RunNote._spawn_app=spawn
        self.app=os.path.join(self.dir,"LOYA_Note.py")
        with open(self.app,"w") as f:f.write("")
    def tearDown(self):
        self.R._abs=self._abs;self.R._spawn_app=self._spawn
        shutil.rmtree(self.dir,ignore_errors=True)
    def test_app_output_goes_to_a_log_file(self):
        self.assertEqual((True,"",123),self.R._launch_app("py",None,self.app))
        self.assertFalse(self.seen["closed_during"],"the log file must be open while the app is spawned")
        self.assertEqual(subprocess.STDOUT,self.seen["stderr"])
        self.assertTrue(self.seen["stdout"].closed,"the launcher closes its own copy after spawning")
        with open(os.path.join(self.dir,"Logs","app_output.log"),encoding="utf-8") as f:self.assertIn("launch ===",f.read())
    def test_an_oversized_output_log_is_started_fresh(self):
        os.makedirs(os.path.join(self.dir,"Logs"))
        path=os.path.join(self.dir,"Logs","app_output.log")
        with open(path,"wb") as f:f.write(b"x"*(self.R.APP_OUTPUT_LOG_MAX+10))
        self.R._launch_app("py",None,self.app)
        self.assertLess(os.path.getsize(path),1000)
    def test_falls_back_to_discarding_output_when_logs_cannot_be_written(self):
        self.R._abs=lambda *p:os.path.join(self.app,*p)   # a file, so Logs/ cannot be created
        self.R._launch_app("py",None,self.app)
        self.assertEqual(subprocess.DEVNULL,self.seen["stdout"]);self.assertEqual(subprocess.DEVNULL,self.seen["stderr"])
if __name__=="__main__":unittest.main()
