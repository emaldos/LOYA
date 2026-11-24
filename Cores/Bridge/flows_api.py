"""Bridge for Chain Diagrams (the visual editor and runner of Action Chains): window.pywebview.api.flows.*
Every method is refused while the app is locked (api._guard_while_locked; nothing here is in _LOCK_OPEN).
The AI-only entry points of flow_service (ai_*) are deliberately not exposed to the page."""
from Cores.Services import flow_service as _flows
IMPORT_FILE_MAX=2*1024*1024
class FlowsAPI:
    def __init__(self):
        self._window=None
    def bind(self,window):
        # Python-only (api._guard_while_locked hides bind from the page): the native file dialogs need the window.
        self._window=window
    def export_file(self,playbook_id):
        """Save a chain export through the native save dialog. -> {"ok","path"}; ok False when the dialog was cancelled."""
        from Cores.Bridge import api as _api
        text=_flows.export_json(playbook_id)
        if self._window is None:raise ValueError("The file dialog is not available.")
        paths=_api._save_dialog(self._window,"JSON","json",_flows.export_name(playbook_id))
        if not paths:return {"ok":False,"path":""}
        out=_flows.file_name_with_ext(paths if isinstance(paths,str) else paths[0],"json")  # never "name.json.json"
        with open(out,"w",encoding="utf-8",newline="\n") as handle:handle.write(text.replace("\r\n","\n"))
        return {"ok":True,"path":out}
    def run_log(self,run_id,since=0,limit=2000):
        return _flows.run_log(run_id,since,limit)
    def run_log_text(self,run_id):
        return _flows.run_log_text(run_id)
    def run_log_export(self,run_id,fmt="text"):
        """Save a run log (fmt "text" -> .log, "json" -> .json) through the native save dialog. -> {"ok","path"}."""
        from Cores.Bridge import api as _api
        name,ext,content=_flows.run_log_file(run_id,fmt)
        if self._window is None:raise ValueError("The file dialog is not available.")
        paths=_api._save_dialog(self._window,"JSON" if ext=="json" else "Log",ext,name)
        if not paths:return {"ok":False,"path":""}
        out=_flows.file_name_with_ext(paths if isinstance(paths,str) else paths[0],ext)
        with open(out,"w",encoding="utf-8",newline="\n") as handle:handle.write(content.replace("\r\n","\n"))
        return {"ok":True,"path":out}
    def policy_get(self):
        return _flows.policy_get()
    def policy_set(self,values):
        return _flows.policy_set(values)
    def import_file(self):
        """Pick a chain export with the native open dialog and import it. -> import_json's result plus ok/path; {"ok":False} when cancelled."""
        from Cores.Bridge import api as _api
        if self._window is None:raise ValueError("The file dialog is not available.")
        paths=_api._open_dialog(self._window,"JSON","json")
        if not paths:return {"ok":False}
        path=paths if isinstance(paths,str) else paths[0]
        import os
        if os.path.getsize(path)>IMPORT_FILE_MAX:raise ValueError("This file is too large to be a chain export.")
        with open(path,"rb") as handle:raw=handle.read(IMPORT_FILE_MAX+1)
        return dict(_flows.import_json(raw),ok=True,path=path)
    def catalog(self):
        return _flows.catalog()
    def list(self):
        return _flows.list_flows()
    def get(self,playbook_id):
        return _flows.get(playbook_id)
    def create(self,name,graph=None,caller=None,template_id=None):
        return {"playbook_id":_flows.create(name,graph,caller,template_id)["playbook_id"]}
    def save(self,playbook_id,graph):
        return _flows.save(playbook_id,graph)
    def validate(self,graph,playbook_id=None):
        return _flows.validate(graph,playbook_id)
    def revert_linear(self,playbook_id):
        return _flows.revert_linear(playbook_id)
    def export_json(self,playbook_id):
        return _flows.export_json(playbook_id)
    def import_json(self,text,name=None):
        return _flows.import_json(text,name)
    def template(self,template_id):
        return _flows.template(template_id)
    def plan(self,playbook_id,graph=None,from_node=None):
        return _flows.plan(playbook_id,graph,from_node)
    def run(self,playbook_id,opts=None):
        opts=dict(opts) if isinstance(opts,dict) else {}
        # The page can never claim to be the AI: that source belongs to the MCP path and its approval gate.
        if opts.get("source") not in ("manual","caller","live"):opts["source"]="manual"
        return _flows.run(playbook_id,opts)
    def run_status(self,run_id,since=0):
        return _flows.run_status(run_id,since)
    def active_runs(self):
        return _flows.active_runs()
    def pause(self,run_id):
        return _flows.pause(run_id)
    def resume(self,run_id):
        return _flows.resume(run_id)
    def stop(self,run_id):
        return _flows.stop(run_id)
    def approve(self,run_id,node_id,approved):
        return _flows.approve(run_id,node_id,approved is True)
    def runs(self,playbook_id=None,limit=30):
        return _flows.runs(playbook_id,limit)
    def run_get(self,run_id):
        return _flows.run_get(run_id)
    def run_delete(self,run_id):
        return _flows.run_delete(run_id)
    def runs_clear(self,playbook_id=None):
        return _flows.runs_clear(playbook_id)
    def mark_reviewed(self,playbook_id):
        return _flows.mark_reviewed(playbook_id)
    def prefs_get(self):
        return _flows.prefs_get()
    def prefs_set(self,values):
        return _flows.prefs_set(values)
    def ai_guide(self):
        return _flows.ai_guide()
    def create_ai_draft(self,name,graph,client=""):
        return _flows.create_ai_draft(name,graph,client)
