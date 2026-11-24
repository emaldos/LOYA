"""Bridge for Settings > Extensions > Kali Linux on WSL (Windows only; on Linux status() reports supported=False and every action refuses).
Every method is refused while the app is locked (api._guard_while_locked); the service checks the lock as well."""
from Cores.Services import wsl_kali_service as _wsl
class WslAPI:
    def status(self,include_ip=False):
        return _wsl.status(include_ip is True)
    def notes(self):
        return {"notes":[_wsl.NOTE_A,_wsl.NOTE_B]}
    def set_enabled(self,enabled,acknowledged=False):
        return _wsl.set_enabled(enabled is True,acknowledged is True)
    def describe(self,action,params=None):
        return _wsl.describe(str(action or ""),params if isinstance(params,dict) else {})
    def wizard_start(self):
        return _wsl.wizard_start()
    def wizard_cancel(self):
        return _wsl.wizard_cancel()
    def wizard_finish(self):
        return _wsl.finish_wizard()
    def enable_feature(self):
        return _wsl.enable_feature()
    def lookup_switches(self):
        return _wsl.lookup_switches_elevated()
    def validate_network(self,values):
        return _wsl.validate_network(values if isinstance(values,dict) else {})
    def apply_network(self,values,confirm_restart=False):
        return _wsl.apply_network(values if isinstance(values,dict) else {},confirm_restart is True)
    def set_default_user(self,username):
        return _wsl.set_default_user(username)
    def verify(self):
        return _wsl.verify()
    def rollback(self):
        return _wsl.rollback_network()
    def restart(self):
        return _wsl.restart()
    def remove_setup(self,unregister=False,confirm_name="",confirm_restart=False):
        return _wsl.remove_setup(unregister is True,str(confirm_name or ""),confirm_restart is True)
    def job_status(self,job_id):
        return _wsl.job_status(job_id)
    def refresh_shells(self):
        return _wsl.refresh_shells()
