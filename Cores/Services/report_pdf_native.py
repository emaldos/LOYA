"""PDF through the app's own web engine: the report's HTML design is printed by WebKitGTK (Linux) or WebView2 (Windows) in a
hidden, script-less web view, then headers, footers, page numbers, the contents' page numbers, links and bookmarks are added.
Anything that goes wrong raises; report_export falls back to the fpdf2 writer."""
import os,sys,json,time,shutil,tempfile,threading,logging,subprocess
if __name__=="__main__":sys.path.insert(0,os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from Cores.Services import report_export as rx
from Cores.Services import report_design as design
from Cores.Services import report_pdf_tools as pt
log=logging.getLogger("loya.report.pdf")
class NativeUnavailable(Exception):pass
MM=72.0/25.4
JOB_TIMEOUT=90.0
def engine():
    """Which print engine this platform has: "webkit", "chromium" or "" (none - use the fallback writer)."""
    if os.environ.get("LOYA_REPORT_PDF_ENGINE","").strip().lower()=="fallback":return ""
    if sys.platform.startswith("linux"):return "webkit"
    if sys.platform.startswith("win"):return "chromium"
    return ""
# ---- Linux: WebKitGTK ----
def _gtk_modules():
    import gi
    try:gi.require_version("Gtk","3.0")
    except ValueError as e:raise NativeUnavailable(str(e))
    try:gi.require_version("WebKit2","4.1")
    except ValueError:
        try:gi.require_version("WebKit2","4.0")
        except ValueError as e:raise NativeUnavailable(str(e))
    from gi.repository import Gtk,GLib,WebKit2
    return Gtk,GLib,WebKit2
def _gtk_print(jobs,timeout,own_settings=False):
    """Print each job {"html","pdf","paper":(w_mm,h_mm),"margins":(t,r,b,l) mm} with an off-screen WebKit view on the GTK main loop."""
    Gtk,GLib,WebKit2=_gtk_modules()
    if own_settings:
        # WebKit positions glyphs on whole pixels when GTK asks for medium/full hinting, which shows as uneven letter spacing in print.
        # Only the helper process changes this: inside the app the setting would re-render the whole interface.
        try:
            gs=Gtk.Settings.get_default()
            if gs is not None:
                gs.set_property("gtk-xft-hinting",1);gs.set_property("gtk-xft-hintstyle","hintslight");gs.set_property("gtk-xft-antialias",1)
        except Exception:pass
    state={"err":None,"win":None,"view":None,"i":0,"started":False,"timer":0}
    done=threading.Event();own_loop=[None]
    def finish(err=None):
        if err and not state["err"]:state["err"]=err
        try:
            if state["win"] is not None:state["win"].destroy()
        except Exception:pass
        state["win"]=state["view"]=None
        done.set()
        if own_loop[0] is not None:own_loop[0].quit()
        return False
    def wait_file(path,cb,tries=0,last=-1):
        # "finished" can arrive a moment before the spooled file is complete: wait until its size stops changing.
        try:size=os.path.getsize(path)
        except OSError:size=-1
        if size>0 and size==last:cb();return False
        if tries>80:finish("The print engine did not write the PDF.");return False
        GLib.timeout_add(60,wait_file,path,cb,tries+1,size)
        return False
    def run_job():
        if done.is_set():return False
        if state["i"]>=len(jobs):finish();return False
        job=jobs[state["i"]]
        try:
            view=state["view"]
            def on_load(v,ev):
                if ev!=WebKit2.LoadEvent.FINISHED or v.loya_job is not job:return
                v.loya_job=None
                # Embedded fonts are decoded on first use; give layout a moment before the print layout is taken.
                GLib.timeout_add(350,do_print)
            def do_print():
                if done.is_set():return False
                try:
                    op=WebKit2.PrintOperation.new(view)
                    ps=Gtk.PrintSettings()
                    ps.set(Gtk.PRINT_SETTINGS_PRINTER,"Print to File")
                    ps.set(Gtk.PRINT_SETTINGS_OUTPUT_FILE_FORMAT,"pdf")
                    ps.set(Gtk.PRINT_SETTINGS_OUTPUT_URI,GLib.filename_to_uri(os.path.abspath(job["pdf"]),None))
                    ps.set_n_copies(1);ps.set_collate(False);ps.set_reverse(False)
                    w,h=job["paper"]
                    size=Gtk.PaperSize.new_custom("loya_report","Report",w,h,Gtk.Unit.MM)
                    setup=Gtk.PageSetup();setup.set_paper_size(size);setup.set_orientation(Gtk.PageOrientation.PORTRAIT)
                    t,r,b,l=job["margins"]
                    setup.set_top_margin(t,Gtk.Unit.MM);setup.set_right_margin(r,Gtk.Unit.MM);setup.set_bottom_margin(b,Gtk.Unit.MM);setup.set_left_margin(l,Gtk.Unit.MM)
                    ps.set_paper_size(size)
                    op.set_print_settings(ps);op.set_page_setup(setup)
                    def ok(_op):
                        def nxt():
                            state["i"]+=1;run_job()
                        wait_file(job["pdf"],nxt)
                    op.connect("finished",ok)
                    op.connect("failed",lambda _op,err:finish("The print engine failed: "+str(getattr(err,"message",err))))
                    state["op"]=op
                    op.print_()
                except Exception as e:finish(f"The print engine failed: {e}")
                return False
            if not state.get("hooked"):
                view.connect("load-changed",on_load_dispatch);state["hooked"]=True
            state["on_load"]=on_load
            view.loya_job=job
            view.load_bytes(GLib.Bytes.new(job["html"].encode("utf-8")),"text/html","UTF-8","about:blank")
        except Exception as e:finish(f"The print engine failed: {e}")
        return False
    def on_load_dispatch(v,ev):
        cb=state.get("on_load")
        if cb:cb(v,ev)
    def start():
        state["started"]=True
        try:
            st=WebKit2.Settings()
            # The document is ours and script-free; scripting is off anyway, and the view has no message handlers (no bridge).
            st.set_enable_javascript(False)
            for name,val in (("set_enable_javascript_markup",False),("set_enable_plugins",False),("set_enable_java",False),("set_enable_html5_local_storage",False),("set_enable_html5_database",False),
                    ("set_enable_page_cache",False),("set_allow_file_access_from_file_urls",False),("set_allow_universal_access_from_file_urls",False),("set_enable_developer_extras",False),
                    ("set_javascript_can_open_windows_automatically",False),("set_enable_webgl",False),("set_enable_media",False),("set_print_backgrounds",True)):
                try:getattr(st,name)(val)
                except Exception:pass
            ctx=None
            try:ctx=WebKit2.WebContext.new_ephemeral()
            except Exception:ctx=None
            view=WebKit2.WebView.new_with_context(ctx) if ctx is not None else WebKit2.WebView()
            view.set_settings(st)
            def policy(_v,decision,kind):
                # Nothing navigates: the only load is the document handed over with load_bytes.
                try:
                    if kind in (WebKit2.PolicyDecisionType.NAVIGATION_ACTION,WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION):
                        act=decision.get_navigation_action();uri=act.get_request().get_uri() or ""
                        if kind==WebKit2.PolicyDecisionType.NEW_WINDOW_ACTION or not uri.startswith("about:"):
                            decision.ignore();return True
                except Exception:pass
                return False
            view.connect("decide-policy",policy)
            view.connect("load-failed",lambda *_a:finish("The report page could not be loaded.") or True)
            view.connect("web-process-terminated",lambda *_a:finish("The print engine stopped unexpectedly."))
            win=Gtk.OffscreenWindow();win.set_default_size(900,1200);win.add(view);win.show_all()
            state["win"]=win;state["view"]=view
            run_job()
        except Exception as e:finish(f"The print engine could not start: {e}")
        return False
    if threading.current_thread() is not threading.main_thread():
        # Inside the running app: the bridge thread hands the work to the GTK main loop and waits.
        GLib.idle_add(start)
        if not done.wait(timeout):
            started=state["started"]
            GLib.idle_add(finish,"timeout")
            raise NativeUnavailable("The print engine timed out." if started else "The interface loop is not running.")
    else:
        ctx=GLib.MainContext.default()
        if GLib.main_depth()>0:raise NativeUnavailable("Cannot print from inside an interface callback.")
        ok=Gtk.init_check(None)
        if not (ok[0] if isinstance(ok,tuple) else ok):raise NativeUnavailable("No display is available.")
        loop=GLib.MainLoop.new(ctx,False);own_loop[0]=loop
        GLib.idle_add(start)
        GLib.timeout_add(int(timeout*1000),finish,"The print engine timed out.")
        loop.run()
    if state["err"]:raise NativeUnavailable(state["err"])
# ---- Windows: WebView2 ----
def _winforms_host():
    """The app's main WinForms form (pywebview's BrowserForm), needed to reach the UI thread and the WebView2 environment."""
    try:
        from webview.platforms import winforms as _wf
    except Exception as e:raise NativeUnavailable(f"WebView2 backend not loaded: {e}")
    forms=[f for f in getattr(_wf.BrowserView,"instances",{}).values() if getattr(f,"browser",None) is not None and getattr(f.browser,"webview",None) is not None]
    if not forms:raise NativeUnavailable("The app window is not available.")
    for f in forms:
        if getattr(f,"uid","")=="master":return f
    return forms[0]
def _same_uri(a,b):
    """file: URIs compared the way the engine reports them back (escaping and drive-letter case may differ)."""
    from urllib.parse import unquote
    norm=lambda u:unquote(u).replace("\\","/").rstrip("/").lower()
    return norm(a)==norm(b)
def _wv2_print(jobs,timeout):
    """Print each job with a hidden WebView2 control that shares the app's WebView2 environment (same user data folder)."""
    host=_winforms_host()
    try:
        import clr  # noqa: F401
        import System.Windows.Forms as WinForms
        from System import Func,Type,Uri,Action
        from System.Drawing import Point,Size
        from Microsoft.Web.WebView2.WinForms import WebView2
    except Exception as e:raise NativeUnavailable(f"WebView2 is not available: {e}")
    if "CoreWebView2" not in dir(host.browser.webview) or host.browser.webview.CoreWebView2 is None:raise NativeUnavailable("WebView2 is not ready.")
    st={"form":None,"wv":None,"err":None,"ready":False,"nav":None,"task":None,"handlers":[]}
    def ui(fn):
        box={}
        def call():
            try:box["v"]=fn()
            except Exception as e:box["e"]=e
            return None
        host.Invoke(Func[Type](call))
        if "e" in box:raise box["e"]
        return box.get("v")
    def create():
        form=WinForms.Form()
        form.ShowInTaskbar=False;form.FormBorderStyle=getattr(WinForms.FormBorderStyle,"None");form.StartPosition=WinForms.FormStartPosition.Manual
        form.Location=Point(-32000,-32000);form.Size=Size(900,1200);form.Opacity=0.0
        wv=WebView2()
        # Same environment as the app's own view: WebView2 refuses a second environment with different options on one user data folder.
        wv.CreationProperties=host.browser.webview.CreationProperties
        wv.Dock=WinForms.DockStyle.Fill
        form.Controls.Add(wv)
        def on_ready(_s,args):
            try:
                if not args.IsSuccess:
                    st["err"]="WebView2 could not start: "+str(args.InitializationException);return
                core=wv.CoreWebView2;s=core.Settings
                s.IsScriptEnabled=False;s.IsWebMessageEnabled=False;s.AreHostObjectsAllowed=False
                s.AreDefaultScriptDialogsEnabled=False;s.AreDevToolsEnabled=False;s.AreDefaultContextMenusEnabled=False;s.IsStatusBarEnabled=False
                def on_new_window(_c,a):a.Handled=True
                core.NewWindowRequested+=on_new_window;st["handlers"].append(on_new_window)
                def on_nav_start(_c,a):
                    # Only the temp file handed to Navigate may load.
                    if st["nav"] is None or _same_uri(str(a.Uri),st["nav"]["uri"]) is False:a.Cancel=True
                core.NavigationStarting+=on_nav_start;st["handlers"].append(on_nav_start)
                def on_nav_done(_c,a):
                    if st["nav"] is not None:st["nav"]["done"]=True;st["nav"]["ok"]=bool(a.IsSuccess)
                core.NavigationCompleted+=on_nav_done;st["handlers"].append(on_nav_done)
                st["ready"]=True
            except Exception as e:st["err"]=f"WebView2 could not be configured: {e}"
        wv.CoreWebView2InitializationCompleted+=on_ready;st["handlers"].append(on_ready)
        # The form is never shown: creating its handle is enough for the control to initialise.
        _h=form.Handle;form.CreateControl();_h2=wv.Handle
        wv.EnsureCoreWebView2Async(None)
        st["form"]=form;st["wv"]=wv
    def wait(cond,limit,what):
        end=time.time()+limit
        while time.time()<end:
            if st["err"]:raise NativeUnavailable(st["err"])
            if cond():return
            time.sleep(0.05)
        raise NativeUnavailable(what)
    def dispose():
        try:
            if st["wv"] is not None:st["wv"].Dispose()
            if st["form"] is not None:st["form"].Dispose()
        except Exception:pass
    try:
        ui(create)
        wait(lambda:st["ready"],min(timeout,30.0),"WebView2 did not start in time.")
        for job in jobs:
            uri=str(Uri(os.path.abspath(job["file"])).AbsoluteUri)
            st["nav"]={"uri":uri,"done":False,"ok":False}
            ui(lambda:st["wv"].CoreWebView2.Navigate(uri))
            wait(lambda:st["nav"]["done"],timeout,"The report page did not load in time.")
            if not st["nav"]["ok"]:raise NativeUnavailable("The report page could not be loaded.")
            time.sleep(0.35)
            def start_print():
                core=st["wv"].CoreWebView2;ps=core.Environment.CreatePrintSettings()
                w,h=job["paper"];t,r,b,l=job["margins"]
                ps.PageWidth=w/25.4;ps.PageHeight=h/25.4
                ps.MarginTop=t/25.4;ps.MarginRight=r/25.4;ps.MarginBottom=b/25.4;ps.MarginLeft=l/25.4
                ps.ShouldPrintBackgrounds=True;ps.ShouldPrintHeaderAndFooter=False;ps.ShouldPrintSelectionOnly=False;ps.ScaleFactor=1.0
                st["task"]=core.PrintToPdfAsync(os.path.abspath(job["pdf"]),ps)
            ui(start_print)
            wait(lambda:bool(st["task"].IsCompleted),timeout,"The print engine timed out.")
            task=st["task"]
            if task.IsFaulted or task.IsCanceled or not bool(task.Result):raise NativeUnavailable("The print engine could not write the PDF.")
            if not os.path.isfile(job["pdf"]) or os.path.getsize(job["pdf"])<200:raise NativeUnavailable("The print engine did not write the PDF.")
    finally:
        try:ui(dispose)
        except Exception:pass
def _gtk_print_worker(jobs,timeout):
    """Run the WebKit print in a helper process (this file as a script): its own GTK loop and font settings, nothing shared with the
    interface, and a hard stop when it hangs. The HTML travels over stdin; only the PDF touches the disk (the caller's private folder)."""
    if getattr(sys,"frozen",False):raise NativeUnavailable("No helper interpreter in a packaged build.")
    payload=json.dumps({"jobs":jobs,"timeout":timeout}).encode("utf-8")
    env=dict(os.environ);env["PYTHONIOENCODING"]="utf-8";env.pop("LOYA_REPORT_PDF_ENGINE",None)
    try:
        p=subprocess.run([sys.executable,os.path.abspath(__file__),"--print-worker"],input=payload,stdout=subprocess.PIPE,stderr=subprocess.PIPE,timeout=timeout+15,env=env,close_fds=True)
    except subprocess.TimeoutExpired:raise NativeUnavailable("The print engine timed out.")
    except OSError as e:raise NativeUnavailable(f"The print helper could not start: {e}")
    out=p.stdout.decode("utf-8","replace").strip().splitlines()
    last=out[-1] if out else ""
    if p.returncode!=0 or not last.startswith("OK"):
        msg=last[4:].strip() if last.startswith("ERR") else (p.stderr.decode("utf-8","replace").strip().splitlines() or ["The print helper failed."])[-1]
        raise NativeUnavailable(msg[:300])
def _worker_main():
    try:
        req=json.loads(sys.stdin.buffer.read().decode("utf-8"))
        _gtk_print(req["jobs"],float(req.get("timeout") or JOB_TIMEOUT),own_settings=True)
        sys.stdout.write("OK\n")
        return 0
    except Exception as e:
        sys.stdout.write("ERR "+str(e).replace("\n"," ")+"\n")
        return 1
def print_jobs(jobs,timeout=JOB_TIMEOUT):
    eng=engine()
    if eng=="webkit":
        if os.environ.get("LOYA_REPORT_PDF_ENGINE","").strip().lower()!="inprocess":
            try:return _gtk_print_worker(jobs,timeout)
            except NativeUnavailable as e:
                log.warning("report pdf: print helper unavailable (%s); printing inside the app",e)
                for j in jobs:
                    try:os.remove(j["pdf"])
                    except OSError:pass
        return _gtk_print(jobs,timeout)
    if eng=="chromium":return _wv2_print(jobs,timeout)
    raise NativeUnavailable("No print engine on this platform.")
# ---- page furniture (stamped over the printed pages) ----
class _Stamp:
    """Headers, footers and the contents' page numbers, drawn with fpdf2 as one overlay page per document page."""
    def __init__(self,doc,sizes):
        from fpdf import FPDF
        self.doc=doc;self.dz=doc["design"];self.sizes=sizes
        self.pdf=FPDF(unit="pt",format=(sizes[0][0],sizes[0][1]));self.pdf.set_auto_page_break(False);self.pdf.set_margins(0,0,0)
        self.pdf.c_margin=0
        self.unicode=self._fonts()
    def _fonts(self):
        pdf=self.pdf;files=design.font_files(self.dz)["body"]
        if not files:
            try:
                from Cores.Services import report_export_pdf as _fp
                sysf=_fp.find_fonts()
                if sysf:files={"":sysf["sans"][""],"B":sysf["sans"]["B"]}
            except Exception:files={}
        if not files:
            self.fam="helvetica";return False
        try:
            pdf.add_font("rb","",files[""]);pdf.add_font("rb","B",files["B"]);self.fam="rb"
        except Exception:
            self.fam="helvetica";return False
        # Scripts the bundled subset does not cover (CJK, Arabic...) come from system fonts when the furniture text needs them.
        need=self._texts()
        try:
            cmap=pdf.fonts["rb"].cmap
            if any(ord(ch) not in cmap for ch in need if not ch.isspace()):
                from Cores.Services import report_export_pdf as _fp
                sysf=_fp.find_fonts() or {};names=[]
                for i,p in enumerate((sysf.get("fallback") or [])+(sysf.get("script") or [])[:3]):
                    try:pdf.add_font(f"fb{i}","",p);names.append(f"fb{i}")
                    except Exception:pass
                if names:pdf.set_fallback_fonts(names,exact_match=False)
        except Exception:pass
        return True
    def _texts(self):
        d=self.doc
        return "".join([d["company"],d["title"],d["classification"],d["footer"],d["banner"]]+[s["title"] for s in d["sections"]])
    def _clean(self,s):
        s=rx._s(s).replace("\n"," ").strip()
        if self.unicode:return s
        from Cores.Services import report_export_pdf as _fp
        return _fp.latin1_safe(s)
    def _fit(self,s,width):
        pdf=self.pdf;s=self._clean(s)
        if pdf.get_string_width(s)<=width:return s
        while len(s)>1 and pdf.get_string_width(s+"...")>width:s=s[:-1]
        return s.rstrip()+"..."
    def text(self,x,baseline,s,size=7.5,style="",color="#5f6b7a",align="L",width=0,spacing=0):
        """One line with its baseline at `baseline` (pt from the top). align R/C position against x."""
        pdf=self.pdf;pdf.set_font(self.fam,style,size);pdf.set_text_color(*design.hex_rgb(color))
        try:pdf.set_char_spacing(spacing)
        except Exception:pass
        s=self._fit(s,width) if width else self._clean(s)
        if not s:return 0
        w=pdf.get_string_width(s)+spacing*max(0,len(s)-1)
        x0=x-w if align=="R" else x-w/2.0 if align=="C" else x
        h=size*1.2
        pdf.set_xy(x0,baseline-(0.5*h+0.3*size))
        pdf.cell(w+1,h,s)
        try:pdf.set_char_spacing(0)
        except Exception:pass
        return w
    def rule(self,x0,x1,y,color,width=0.5):
        pdf=self.pdf;pdf.set_draw_color(*design.hex_rgb(color));pdf.set_line_width(width);pdf.line(x0,y,x1,y)
    def page(self,index,total,section,toc_numbers,furniture=True):
        """index: 0-based page; section: running title; toc_numbers: [(baseline_from_top, text, bold)]."""
        W,H=self.sizes[index];pdf=self.pdf;dz=self.dz;doc=self.doc;m=dz["margins"]
        pdf.add_page(format=(W,H))
        if not furniture:return
        L=m["left"]*MM;R=W-m["right"]*MM;th=dz["theme"]
        muted=dz["muted"];rule=dz["rule"]
        banner=doc["banner"] or ""
        # header
        hy=13.2*MM
        if th=="corporate":
            if banner:
                pdf.set_fill_color(*design.hex_rgb(dz["accent"]));pdf.rect(0,0,W,5.2*MM,"F")
                self.text(W/2.0,3.55*MM,banner.upper(),6,"B",dz["on_accent"],"C",W-30*MM,0.9)
            self.text(L,hy,doc["company"],7.5,"B",dz["ink"],"L",(R-L)*0.45)
            self.text(R,hy,section or doc["title"],7.5,"",muted,"R",(R-L)*0.5)
            self.rule(L,R,hy+2.2*MM,rule)
        elif th=="modern":
            pdf.set_fill_color(*design.hex_rgb(dz["accent"]));pdf.rect(L,hy-2.5*MM,2.6*MM,2.6*MM,"F")
            self.text(L+4.4*MM,hy,doc["company"].upper(),7,"B",dz["text"],"L",(R-L)*0.4,0.8)
            self.text(R,hy,(section or doc["title"]).upper(),7,"",muted,"R",(R-L)*0.5,0.8)
            if banner:self.text(W/2.0,5.6*MM,banner.upper(),6,"B",muted,"C",W-30*MM,0.9)
        else:
            if banner:self.text(W/2.0,5.6*MM,banner.upper(),6,"",muted,"C",W-30*MM,0.9)
            self.text(L,hy,doc["company"],7.5,"",muted,"L",(R-L)*0.45)
            self.text(R,hy,section or doc["title"],7.5,"",muted,"R",(R-L)*0.5)
            self.rule(L,R,hy+2.2*MM,dz["text"],0.35)
        # footer
        fy=H-9.2*MM;label=f"Page {index+1} of {total}"
        if th=="modern":
            self.text(L,fy,doc["classification"].upper(),7,"B",dz["text"],"L",(R-L)*0.3,0.8)
            tw=self.text(R,fy,f"/ {total:02d}",7,"",muted,"R")
            self.text(R-tw-3,fy,f"{index+1:02d}",11,"B",dz["accent"] if design.contrast(dz["accent"],"#ffffff")>=3 else dz["text"],"R")
            self.text(W/2.0,fy,doc["footer"],6.8,"",muted,"C",(R-L)*0.42)
        else:
            self.rule(L,R,fy-4.2*MM,rule if th=="corporate" else dz["text"],0.5 if th=="corporate" else 0.35)
            self.text(L,fy,doc["classification"],7.5,"B",dz["ink"] if th=="corporate" else dz["text"],"L",(R-L)*0.28)
            self.text(R,fy,label,7.5,"",muted,"R")
            self.text(W/2.0,fy,doc["footer"],6.8,"",muted,"C",(R-L)*0.44)
        for base,txt,bold in toc_numbers:
            self.text(R,base,txt,9.4 if bold else 8.6,"B" if bold else "",dz["text"],"R")
    def output(self):return bytes(self.pdf.output())
def _read(path):
    with open(path,"rb") as f:return f.read()
def write_pdf(doc,out_path,timeout=JOB_TIMEOUT):
    """Render `doc` (report_export.prepare) to out_path with the native engine. Returns {"pages":n,"toc_numbers":bool,"engine":..}."""
    eng=engine()
    if not eng:raise NativeUnavailable("No print engine on this platform.")
    from Cores.Services import report_export_html as rh
    o=doc["options"];dz=doc["design"];m=dz["margins"]
    paper=design.PAGE_MM["Letter" if o["page_size"]=="Letter" else "A4"]
    tmp=tempfile.mkdtemp(prefix="loya_report_")
    try:
        try:os.chmod(tmp,0o700)
        except OSError:pass
        jobs=[];cover_pdf=""
        if o["include_cover"]:
            html,_m=rh.render(doc,{"engine":eng,"part":"cover"});cover_pdf=os.path.join(tmp,"cover.pdf")
            jobs.append({"html":html,"pdf":cover_pdf,"paper":paper,"margins":(0,0,0,0)})
        html,marks=rh.render(doc,{"engine":eng,"part":"body"});body_pdf=os.path.join(tmp,"body.pdf")
        jobs.append({"html":html,"pdf":body_pdf,"paper":paper,"margins":(m["top"],m["right"],m["bottom"],m["left"])})
        if eng=="chromium":
            # WebView2 navigates to a file; it lives in the private temp folder and is removed with it below.
            for i,j in enumerate(jobs):
                j["file"]=os.path.join(tmp,f"part{i}.html")
                with open(j["file"],"w",encoding="utf-8",newline="\n") as f:f.write(j["html"])
        print_jobs(jobs,timeout)
        return finish_pdf(doc,eng,cover_pdf,body_pdf,marks,out_path)
    finally:
        shutil.rmtree(tmp,ignore_errors=True)
def finish_pdf(doc,eng,cover_pdf,body_pdf,marks,out_path):
    """The printed parts -> the final PDF: cover + body, page furniture stamped on, contents numbered and linked, bookmarks, properties."""
    o=doc["options"];m=doc["design"]["margins"]
    if True:
        body=pt.Reader(_read(body_pdf));bpages=body.pages()
        if not bpages:raise NativeUnavailable("The print engine produced an empty document.")
        parts=[];first=0
        if cover_pdf:
            cov=pt.Reader(_read(cover_pdf))
            if cov.pages():parts.append((cov,[0]));first=1
        parts.append((body,list(range(len(bpages)))))
        total=first+len(bpages)
        sizes=[]
        if first:
            mb=parts[0][0].media_box(parts[0][0].pages()[0][1]);sizes.append((mb[2]-mb[0],mb[3]-mb[1]))
        for _n,p in bpages:
            mb=body.media_box(p);sizes.append((mb[2]-mb[0],mb[3]-mb[1]))
        # Where did every heading and contents row land?
        found=[]
        for i,(_n,p) in enumerate(bpages):
            try:ms=pt.find_markers(body.page_content(p))
            except Exception:ms=[]
            ms.sort(key=lambda t:-t[2])
            found.extend((code,first+i,x,y) for code,x,y in ms)
        located=len(found)==len(marks) and all(f[0]==mk["code"] for f,mk in zip(found,marks))
        toc_rows={};targets={};order=[]
        if located:
            for f,mk in zip(found,marks):
                (toc_rows if mk["kind"]=="toc" else targets)[mk["anchor"]]=f
                if mk["kind"]=="target":order.append(mk["anchor"])
        elif marks:log.warning("report pdf: %d of %d position markers found; page references are left out",len(found),len(marks))
        stamp=_Stamp(doc,sizes)
        sec_title={s["anchor"]:s["title"] for s in doc["sections"]}
        starts=sorted((targets[a][1],n,a) for n,a in enumerate(order) if a in sec_title) if located else []
        H=lambda i:sizes[i][1]
        links=[];numbers={}
        for anchor,(code,pg,x,y) in toc_rows.items():
            tg=targets.get(anchor)
            if not tg:continue
            l1=anchor in sec_title
            numbers.setdefault(pg,[]).append((H(pg)-y,str(tg[1]+1),l1))
            links.append({"page":pg,"rect":[m["left"]*MM,y-3.5,sizes[pg][0]-m["right"]*MM,y+9.5],"to":tg[1],"top":min(H(tg[1]),tg[3]+26)})
        for i in range(total):
            if first and i==0:stamp.page(i,total,"",[],False);continue
            title=""
            for pg,_n2,a in starts:
                if pg<=i:title=sec_title[a]
            if not title and o["include_toc"] and doc["toc"] and (not starts or i<starts[0][0]):title="Contents"
            stamp.page(i,total,title,numbers.get(i,[]))
        overlay=pt.Reader(stamp.output())
        outline=[]
        if located:
            fnum={f["anchor"]:f for f in doc["findings"]}
            for a in order:
                tg=targets[a]
                if a in sec_title:
                    sec=next(s for s in doc["sections"] if s["anchor"]==a)
                    outline.append({"title":sec["heading"],"page":tg[1],"top":min(H(tg[1]),tg[3]+30),"level":1})
                elif a in fnum:outline.append({"title":f"{fnum[a]['number']}  {fnum[a]['title']}","page":tg[1],"top":min(H(tg[1]),tg[3]+26),"level":2})
        meta=doc["meta"];c=doc["cover"]
        info={"Title":doc["title"],"Author":c.get("authors") or doc["company"],"Subject":" - ".join(x for x in (meta["report_type"],meta["client"]) if x),
            "Keywords":", ".join(x for x in (doc["classification"],meta["project_code"]) if x),"Creator":"LOYA NG","Producer":"LOYA NG ("+("WebKitGTK" if eng=="webkit" else "WebView2")+" print engine)",
            "CreationDate":pt.Raw(time.strftime("(D:%Y%m%d%H%M%S)").encode("ascii"))}
        n=pt.assemble(out_path,parts,overlay,links,outline,info)
        return {"engine":eng,"pages":n,"toc_numbers":bool(located and toc_rows),"bookmarks":len(outline)}
if __name__=="__main__":
    if "--print-worker" in sys.argv:sys.exit(_worker_main())
