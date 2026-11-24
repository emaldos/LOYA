"""Bridge for the Chains page's Run History sub-tab and the chain/run bundle export and import: window.pywebview.api.chainHistory.*
Every method is refused while the app is locked (api._guard_while_locked; nothing here is in _LOCK_OPEN). Files go through the
app's native save/open dialogs (api._save_dialog/_open_dialog), which work on Windows (WebView2) and Linux (WebKitGTK)."""
import os,threading,uuid
from Cores.Services import chain_history as _hist
_PENDING_MAX=3
class ChainHistoryAPI:
    def __init__(self):
        self._window=None
        self._pending={}      # token -> raw bytes of a picked file waiting for import_apply (never sent back to the page)
        self._lock=threading.Lock()
    def bind(self,window):
        # Python-only (api._guard_while_locked hides bind from the page): the native file dialogs need the window.
        self._window=window
    def list(self,filters=None):
        return _hist.list_runs(filters if isinstance(filters,dict) else {})
    def facets(self):
        return _hist.facets()
    def detail(self,run_id):
        return _hist.run_detail(str(run_id or ""))
    def delete(self,run_ids):
        return _hist.delete_runs(run_ids if isinstance(run_ids,list) else [run_ids])
    def clear(self,playbook_id=None,chain_name=None):
        return _hist.clear_runs(playbook_id,chain_name or None)
    def export_file(self,spec=None):
        """spec={"chains":[ids]|"all"|None,"runs":[run ids]|"all"|None,"runs_of_chain":id|None,"include_logs":bool}.
        A section is exported when its key is present. -> {"ok","path","chains","runs"}; ok False when the dialog was cancelled."""
        from Cores.Bridge import api as _api
        from Cores.Services import flow_service as _flows
        spec=spec if isinstance(spec,dict) else {}
        want_chains="chains" in spec and spec.get("chains") is not None
        want_runs=("runs" in spec and spec.get("runs") is not None) or spec.get("runs_of_chain") is not None
        if not want_chains and not want_runs:raise ValueError("Pick the chains or runs to export.")
        bundle=_hist.export_bundle(spec.get("chains"),spec.get("runs"),include_chains=want_chains,include_runs=want_runs,runs_of_chain=spec.get("runs_of_chain"),include_logs=spec.get("include_logs") is not False)
        if not bundle["chains"] and not bundle["runs"]:raise ValueError("There is nothing to export.")
        if self._window is None:raise ValueError("The file dialog is not available.")
        paths=_api._save_dialog(self._window,"LOYA chain bundle","json",_hist.export_file_name(bundle))
        if not paths:return {"ok":False,"path":""}
        out=_flows.file_name_with_ext(paths if isinstance(paths,str) else paths[0],"json")   # never "name.json.json"
        with open(out,"w",encoding="utf-8",newline="\n") as handle:handle.write(_hist.bundle_text(bundle))
        _hist._audit("chain_bundle_export",f"{len(bundle['chains'])} chain(s) and {len(bundle['runs'])} run(s) exported to {os.path.basename(out)}")
        return {"ok":True,"path":out,"chains":len(bundle["chains"]),"runs":len(bundle["runs"])}
    def _keep(self,raw,name):
        token=uuid.uuid4().hex
        with self._lock:
            self._pending[token]=(raw,name)
            for old in list(self._pending)[:-_PENDING_MAX]:self._pending.pop(old,None)
        return token
    def import_pick(self):
        """Pick a bundle (or a single-chain export) with the native open dialog and preview it. Nothing is written yet.
        -> {"ok":False} when cancelled, else preview() plus {"ok","token","name"} for import_apply."""
        from Cores.Bridge import api as _api
        if self._window is None:raise ValueError("The file dialog is not available.")
        paths=_api._open_dialog(self._window,"LOYA chain bundle","json")
        if not paths:return {"ok":False}
        path=paths if isinstance(paths,str) else paths[0]
        if os.path.getsize(path)>_hist.IMPORT_MAX_BYTES:raise ValueError("This file is too large to import (the limit is 64 MB).")
        with open(path,"rb") as handle:raw=handle.read(_hist.IMPORT_MAX_BYTES+1)
        info=_hist.preview(raw)
        return dict(info,ok=True,token=self._keep(raw,os.path.basename(path)),name=os.path.basename(path))
    def import_preview_text(self,text):
        """The same preview for text the page read itself (a dropped file)."""
        raw=str(text or "")
        info=_hist.preview(raw)
        return dict(info,ok=True,token=self._keep(raw,"pasted"),name="")
    def import_apply(self,token,options=None):
        with self._lock:item=self._pending.pop(str(token or ""),None)
        if item is None:raise ValueError("Pick the file again: the import expired.")
        result=_hist.import_bundle(item[0],options if isinstance(options,dict) else {})
        _hist._audit("chain_bundle_import",f"{item[1][:120]}: {len(result['chains']['created'])} chain(s) created, {len(result['chains']['replaced'])} replaced, {result['runs']['imported']} run(s) imported")
        return result
    def import_cancel(self,token):
        with self._lock:return self._pending.pop(str(token or ""),None) is not None
