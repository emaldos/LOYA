import os,sys,tempfile,shutil
ROOT=os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:sys.path.insert(0,ROOT)
from Cores import common_db
class IsolatedData:
    def __init__(self):
        self.dir=None
        self._original=None
    def start(self):
        self.dir=tempfile.mkdtemp(prefix="loya_test_")
        self._original=common_db.data_dir
        common_db.data_dir=lambda:self.dir
        # The storage rebuild reads encryption state from settings.json on every DB open: never let a test see the real one.
        from Cores.Update import health_check as _hc
        self._settings_path=_hc.settings_path
        _hc.settings_path=lambda:os.path.join(self.dir,"settings.json")
        self._session_key=common_db.session_key();common_db.set_session_key(None)
        # Backups (pre-encryption .loyabak, data backups) stay in the scratch area, never the app's real Backups/.
        self._backups_dir=common_db.backups_dir
        common_db.backups_dir=lambda:(os.makedirs(os.path.join(self.dir,"Backups"),exist_ok=True),os.path.join(self.dir,"Backups"))[1]
        # A developer checkout may hold the real 20 MB offline CVE index seed (Assets/cve, git-ignored). Tests must not install it:
        # it would change what CVE lookups return and unpack 96 MB per test. Tests that want a seed set cve_index.seed_dir themselves.
        try:
            from Cores.Services import cve_index
            self._seed_dir=cve_index.seed_dir
            cve_index.seed_dir=lambda:os.path.join(self.dir,"no_cve_seed")
            cve_index._state["checked"]=None
        except Exception:self._seed_dir=None
        return self.dir
    def stop(self):
        if self._original is not None:common_db.data_dir=self._original
        if getattr(self,"_settings_path",None) is not None:
            from Cores.Update import health_check as _hc
            _hc.settings_path=self._settings_path;self._settings_path=None
            common_db.set_session_key(self._session_key)
            common_db.backups_dir=self._backups_dir
        if getattr(self,"_seed_dir",None) is not None:
            from Cores.Services import cve_index
            cve_index.seed_dir=self._seed_dir;cve_index._state["checked"]=None
            self._seed_dir=None
        if self.dir:shutil.rmtree(self.dir,ignore_errors=True)
        self.dir=None
        self._original=None
