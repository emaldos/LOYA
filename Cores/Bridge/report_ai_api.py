"""Bridge module api.reportAI - AI help on the Reporting page. Nothing is sent to a provider before run/run_start, which the UI only calls from its consent dialog."""
from Cores.Services import report_ai as _svc
def _need_digest(digest):
    d=str(digest or "").strip().lower()
    if len(d)!=64 or any(c not in "0123456789abcdef" for c in d):raise ValueError("Review what will be sent first (the AI consent dialog).")
    return d
class ReportAIAPI:
    def __init__(self):self._window=None
    def bind(self,window):self._window=window
    def status(self):return _svc.status()
    def preview(self,action,payload=None):return _svc.preview(action,payload)
    # From the page a run always needs the digest of the preview the operator confirmed: without it nothing pins what is sent to
    # what was shown, so a call that skips the consent dialog is refused.
    def run(self,action,payload=None,digest=None):return _svc.run(action,payload,_need_digest(digest))
    def run_start(self,action,payload=None,digest=None):return _svc.run_start(action,payload,_need_digest(digest))
    def run_poll(self,job_id):return _svc.run_poll(job_id)
    def run_cancel(self,job_id):return _svc.run_cancel(job_id)
