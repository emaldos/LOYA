"""Bridge module api.reportsIO - report export, preview and import (see the reporting contract)."""
import os,time
from Cores.Services import report_export as _rx
_SAVE_LABELS={"pdf":"PDF","docx":"Word Document","html":"HTML","markdown":"ZIP","json":"JSON","csv":"CSV","xlsx":"Excel Workbook","sarif":"SARIF"}
class ReportsIOAPI:
    def __init__(self):
        self._window=None
        self._picked=set()
    def bind(self,window):self._window=window
    def _save(self,label,ext,default):
        from Cores.Bridge import api as _api
        return _api._save_dialog(self._window,label,ext,default)
    def _run(self,fn):
        # Anything a writer raises reaches the page as a readable message instead of a bare traceback string.
        try:return fn()
        except ValueError:raise
        except Exception as e:
            from Cores import common_db
            if isinstance(e,getattr(common_db,"DatabaseLocked",())):raise
            raise ValueError(f"The export failed: {e}")
    def formats(self):return [dict(f) for f in _rx.FORMATS]
    # Last export-dialog choices that are not report defaults (reports.defaults_set owns those). Stored next to them in
    # settings.json under reports.export; defaults_set keeps keys it does not know.
    def _prefs_norm(self,src):
        src=src if isinstance(src,dict) else {}
        out={}
        if src.get("format") in _rx.FORMAT_BY_ID:out["format"]=src["format"]
        for k in ("include_cover","redact","embed_fonts"):
            if isinstance(src.get(k),bool):out[k]=src[k]
        fs=src.get("findings_status")
        if isinstance(fs,(list,tuple)):
            fs=[x for x in _rx.STATUSES if x in fs]
            if fs:out["findings_status"]=fs
        return out
    def _settings_path(self):
        from Cores import common_db
        return os.path.join(common_db.data_dir(),"settings.json")
    def export_prefs_get(self):
        from Cores import settings_lock
        d=settings_lock.read_json(self._settings_path(),{})
        r=d.get("reports") if isinstance(d,dict) and isinstance(d.get("reports"),dict) else {}
        return self._prefs_norm(r.get("export"))
    def export_prefs_set(self,patch):
        from Cores import settings_lock
        norm=self._prefs_norm(patch)
        def mutate(d):
            r=d.get("reports") if isinstance(d.get("reports"),dict) else {}
            cur=self._prefs_norm(r.get("export"));cur.update(norm)
            r["export"]=cur;d["reports"]=r
            norm.update(cur)
        if not settings_lock.update_json(self._settings_path(),mutate):raise ValueError("Could not save the export preferences.")
        return norm
    def _options(self,options):
        """Caller options plus the remembered "Mask credentials and secrets" choice (on unless the user turned it off) for callers
        that do not say, such as the in-app preview."""
        o=dict(options) if isinstance(options,dict) else {}
        o.pop("_result",None)
        if not isinstance(o.get("redact"),bool) or not isinstance(o.get("embed_fonts"),bool):
            try:prefs=self.export_prefs_get()
            except Exception:prefs={}
            if not isinstance(o.get("redact"),bool):o["redact"]=prefs.get("redact",True)
            if not isinstance(o.get("embed_fonts"),bool):o["embed_fonts"]=prefs.get("embed_fonts",True)
        return o
    def themes(self):
        """Built-in report themes with their fonts, cover styles and preview colours (for the theme picker)."""
        from Cores.Services import report_design as _design
        return _design.themes()
    def pdf_engine(self):
        """Which PDF engine an export will try first: {"engine":"webkit"|"chromium"|"fallback","label":...}."""
        from Cores.Services import report_pdf_native as _native
        eng=_native.engine() or "fallback"
        return {"engine":eng,"label":{"webkit":"WebKitGTK print engine","chromium":"WebView2 print engine"}.get(eng,"Basic PDF writer")}
    def export_ex(self,report_id,fmt,options=None):
        """export() that also says how the file was made: {"path","format","engine","native":bool,"reason","pages","message"} or None when cancelled."""
        if fmt not in _rx.FORMAT_BY_ID:raise ValueError("Unsupported format.")
        report=_rx.load_report(report_id)
        out=self._save(_SAVE_LABELS[fmt],_rx.FORMAT_BY_ID[fmt]["ext"],_rx.default_filename(report,fmt))
        if not out:return None
        o=self._options(options);res={}
        if fmt=="pdf":
            o.setdefault("pdf_engine","auto");o["_result"]=res
        path=self._run(lambda:_rx.render(report,fmt,out,o))
        info={"path":path,"format":fmt,"engine":res.get("engine",""),"native":res.get("engine") in ("webkit","chromium"),"reason":res.get("reason",""),"pages":res.get("pages",0),"message":""}
        if fmt=="pdf":
            info["message"]="PDF created with the built-in print engine." if info["native"] else "PDF created with the basic PDF writer (the print engine was not available)."
        self._last_export=info
        return info
    def last_export(self):return dict(getattr(self,"_last_export",None) or {})
    def sniff(self,staged):
        """Is a staged upload one of the reporting file formats? Strict (by its "format" marker) so other JSON imports are never hijacked."""
        from Cores.Bridge import api as _api
        from Cores.Services import report_import as _imp
        p=_api._staged_path(staged)
        if not p.lower().endswith(".json"):return {"kind":""}
        try:
            with open(p,"rb") as f:head=f.read(2048).decode("utf-8","ignore")
        except OSError:return {"kind":""}
        import re
        m=re.search(r'"format"\s*:\s*"(loya-report[a-z\-]*)"',head)
        return {"kind":_imp.classify({"format":m.group(1)}) if m else ""}
    def export(self,report_id,fmt,options=None):
        if fmt not in _rx.FORMAT_BY_ID:raise ValueError("Unsupported format.")
        report=_rx.load_report(report_id)
        out=self._save(_SAVE_LABELS[fmt],_rx.FORMAT_BY_ID[fmt]["ext"],_rx.default_filename(report,fmt))
        if not out:return None
        o=self._options(options);res={}
        if fmt=="pdf":
            o.setdefault("pdf_engine","auto");o["_result"]=res
        path=self._run(lambda:_rx.render(report,fmt,out,o))
        self._last_export={"path":path,"format":fmt,"engine":res.get("engine",""),"native":res.get("engine") in ("webkit","chromium"),"reason":res.get("reason",""),"pages":res.get("pages",0),"message":""}
        return path
    def preview_html(self,report_id,options=None):
        report=_rx.load_report(report_id)
        return self._run(lambda:_rx.build_html(report,self._options(options)))
    def export_many(self,report_ids=None,fmt="json"):
        if fmt not in _rx.FORMAT_BY_ID:raise ValueError("Unsupported format.")
        from Cores.Services import reports_service as _svc
        ids=list(report_ids) if isinstance(report_ids,(list,tuple)) and report_ids else [r["id"] for r in _svc.list_reports()]
        if not ids:raise ValueError("There are no reports to export yet.")
        reports=[_svc.get_report(i) for i in ids]
        stamp=time.strftime("%Y-%m-%d")
        if fmt=="json":out=self._save("JSON","json",f"LOYA-Reports-{stamp}.json")
        else:out=self._save("ZIP","zip",f"LOYA-Reports-{fmt}-{stamp}.zip")
        if not out:return None
        o=self._options(None)
        if fmt=="pdf":o["pdf_engine"]="auto"
        return self._run(lambda:_rx.render_many(reports,fmt,out,o))
    def export_templates(self,ids=None):
        from Cores.Services import report_import as _imp
        payload=_imp.build_templates_export(ids if isinstance(ids,(list,tuple)) and ids else None)
        out=self._save("JSON","json",f"LOYA-Report-Templates-{time.strftime('%Y-%m-%d')}.json")
        if not out:return None
        return self._run(lambda:_rx.atomic_write(out,lambda p:_rx._write_json(payload,p)))
    def export_library(self):
        from Cores.Services import report_import as _imp
        payload=_imp.build_library_export()
        out=self._save("JSON","json",f"LOYA-Findings-Library-{time.strftime('%Y-%m-%d')}.json")
        if not out:return None
        return self._run(lambda:_rx.atomic_write(out,lambda p:_rx._write_json(payload,p)))
    def _pick(self,kind,staged):
        from Cores.Bridge import api as _api
        if staged:return _api._staged_path(staged)
        if kind=="findings_csv":paths=_api._pick_paths(self._window,"CSV","csv")
        elif kind in ("report_json","templates","library"):paths=_api._pick_paths(self._window,"JSON","json")
        else:
            import webview
            paths=self._window.create_file_dialog(webview.FileDialog.OPEN,directory=_api._dialog_dir(),file_types=(_api._file_types("Report files","json","csv"),))
            if paths:_api._remember_dialog_dir(os.path.dirname(paths if isinstance(paths,str) else paths[0]))
        if not paths:return None
        return paths if isinstance(paths,str) else paths[0]
    def pick_import(self,kind="auto",staged=None):
        from Cores.Services import report_import as _imp
        kind=kind or "auto"
        if kind!="auto" and kind not in _imp.KINDS:raise ValueError("Unsupported import type.")
        path=self._pick(kind,staged)
        if not path:return None
        info=_imp.summarize(path,kind)
        # apply_import only accepts a path this module handed out, so the page cannot aim the importer at an arbitrary file.
        self._picked.add(os.path.realpath(path))
        return {"path":path,"name":os.path.basename(path),"kind":info["kind"],"label":info["label"],"summary":info["summary"]}
    def apply_import(self,path,kind,options=None):
        from Cores.Services import report_import as _imp
        real=os.path.realpath(str(path or ""))
        if real not in self._picked or not os.path.isfile(real):raise ValueError("That file is no longer available. Choose it again.")
        if kind not in _imp.KINDS:raise ValueError("Unsupported import type.")
        try:res=_imp.apply(real,kind,options if isinstance(options,dict) else None)
        except ValueError:raise
        except Exception as e:
            from Cores import common_db
            if isinstance(e,getattr(common_db,"DatabaseLocked",())):raise
            raise ValueError(f"The import failed: {e}")
        self._picked.discard(real)
        return res
