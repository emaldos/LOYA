import os,re,json,time,sys,subprocess,logging,base64,threading
import webview
_diag_log=logging.getLogger("Note")
from Cores.Theme import tokens as _tokens
from Cores.Services import dashboard_service as _dashboard
from Cores.Services import notes_service as _notes_svc
from Cores.Services import commands_service as _commands_svc
from Cores.Services import playbooks_service as _playbooks_svc
from Cores.Services import flow_service as _flow_svc
from Cores.Services import targets_service as _targets_svc
from Cores.Services import search_service as _search_svc
from Cores.Services import quick_space_service as _quick_svc
from Cores.Services import settings_service as _settings_svc
from Cores.Services import templates_service as _templates_svc
from Cores.Services import report_service as _report_svc
from Cores.Services import security_service as _security_svc
from Cores.Services import terminal_service as _terminal_svc
from Cores.Services import ai_service as _ai_svc
from Cores.Services import ai_chat_service as _ai_chat_svc
from Cores.Services import ai_sessions_service as _ai_sessions_svc
from Cores.Services import mcp_local_service as _mcp_local_svc
from Cores.Services import ai_index_service as _ai_index_svc
from Cores.Services import semantic_search_service as _semantic_svc
from Cores import recycle_bin as _recycle_bin
from Cores import common_db as _common_db
from Cores import settings_lock as _settings_lock
from Cores import os_toast as _os_toast
from Cores.Update import update_service as _update_svc
from Cores.Update import update_helpers as _update_helpers
from Cores.Update import backup_restore as _update_backup
from Cores.Update import health_check as _health_check
from Cores.Update import recovery as _recovery
MIN_W,MIN_H=460,380
MINI_MIN_W,MINI_MIN_H=320,240
MINI_COLLAPSED_H=60
_windows={}
def _root(*p):return os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)),"..","..",*p))
def _settings_path():return _root("Data","settings.json")
def read_settings():
    try:
        with open(_settings_path(),"r",encoding="utf-8") as f:
            d=json.load(f)
        return d if isinstance(d,dict) else {}
    except Exception:
        return {}
def write_settings(d):
    # Through the shared lock and a unique temp file, so a parallel writer (theme, terminal, Mini, security) can't interleave.
    with _settings_lock.SETTINGS_LOCK:_settings_lock.write_json(_settings_path(),d)
def load_window_geometry():
    g=read_settings().get("window",{})
    return g if isinstance(g,dict) else {}
def _destroy_soon(window,delay=0.15):
    threading.Timer(delay,window.destroy).start()
_IS_LINUX=sys.platform.startswith("linux")
def _gtk_view(window):
    try:
        from webview.platforms.gtk import BrowserView
        return BrowserView.instances.get(window.uid)
    except Exception:return None
def _on_gtk_main_thread():
    if threading.current_thread() is threading.main_thread():return True
    try:
        from gi.repository import GLib
        return bool(GLib.MainContext.default().is_owner())
    except Exception:return False
def _run_on_gtk_main(fn,timeout=2.0):
    if _on_gtk_main_thread():return fn()
    from gi.repository import GLib
    box={};done=threading.Event()
    def call():
        try:box["value"]=fn()
        except Exception as e:box["error"]=e
        finally:done.set()
        return False
    GLib.idle_add(call)
    if not done.wait(timeout):return None
    if "error" in box:raise box["error"]
    return box.get("value")
def _gtk_unmaximize(window):
    if not _IS_LINUX:return False
    view=_gtk_view(window)
    if view is None:return False
    try:
        from gi.repository import GLib
        def unmaximize():
            view.window.unmaximize()
            return False
        GLib.idle_add(unmaximize)
        return True
    except Exception:return False
def _file_types(label,*exts):
    pats=[]
    for e in exts:
        pats.append(f"*.{e}")
        if _IS_LINUX and e.upper()!=e:pats.append(f"*.{e.upper()}")
    return f"{label} ({';'.join(pats)})"
def _with_extension(path,ext):
    if not path or not ext:return path
    head,base=os.path.split(path)
    if base.lower().endswith("."+ext.lower()):return path
    return os.path.join(head,f"{base.rstrip('.') or base}.{ext}")
def _default_dialog_dir():
    try:
        from gi.repository import GLib
        d=GLib.get_user_special_dir(GLib.UserDirectory.DIRECTORY_DOCUMENTS)
        if d and os.path.isdir(d):return d
    except Exception:pass
    return os.path.expanduser("~")
def _dialog_dir():
    if not _IS_LINUX:return ""
    d=read_settings().get("last_dialog_dir")
    if isinstance(d,str) and d and os.path.isdir(d):return d
    return _default_dialog_dir()
def _remember_dialog_dir(path):
    if not _IS_LINUX or not path:return
    d=os.path.abspath(path)
    if not os.path.isdir(d):return
    with _settings_lock.SETTINGS_LOCK:
        s=read_settings()
        if s.get("last_dialog_dir")==d:return
        s["last_dialog_dir"]=d
        write_settings(s)
def _first_path(paths):
    if not paths:return None
    return paths if isinstance(paths,str) else paths[0]
def _folder_dialog(window):
    folder=_first_path(window.create_file_dialog(webview.FileDialog.FOLDER,directory=_dialog_dir()))
    if folder:_remember_dialog_dir(folder)
    return folder
# Drag-and-drop / browse imports: the page cannot hand Python a real file path (WebKitGTK and WebView2 both hide it),
# so the dropped bytes are staged into a private temp folder and the normal parse path reads them from there.
UPLOAD_MAX_BYTES=100*1024*1024
_upload_state={"dir":None}
_upload_lock=threading.Lock()
def _upload_dir():
    with _upload_lock:
        d=_upload_state["dir"]
        if not d or not os.path.isdir(d):
            import tempfile,atexit,shutil
            d=tempfile.mkdtemp(prefix="loya_import_")
            _upload_state["dir"]=d
            atexit.register(shutil.rmtree,d,True)
        return d
def _stage_upload(name,b64):
    base=os.path.basename(str(name or "").replace("\\","/")).strip()
    base="".join(c for c in base if c not in '<>:"|?*\x00').strip(". ") or "import.bin"
    try:data=base64.b64decode(b64 or "",validate=True)
    except Exception:raise ValueError("The dropped file could not be read.")
    if not data:raise ValueError("The dropped file is empty.")
    if len(data)>UPLOAD_MAX_BYTES:raise ValueError(f"The file is larger than {UPLOAD_MAX_BYTES//(1024*1024)} MB.")
    sub=os.path.join(_upload_dir(),f"{int(time.time()*1000)}_{os.getpid()}_{threading.get_ident()}")
    os.makedirs(sub,exist_ok=True)
    p=os.path.join(sub,base)
    with open(p,"wb") as f:f.write(data)
    return p
def _staged_path(p):
    """Only files this process staged may skip the dialog - the page must not be able to point the importer at an arbitrary path."""
    d=_upload_state["dir"]
    if not d or not p:raise ValueError("That file is no longer available. Drop it again.")
    real=os.path.realpath(str(p));root=os.path.realpath(d)
    if os.path.commonpath([real,root])!=root or real==root or not os.path.isfile(real):raise ValueError("That file is no longer available. Drop it again.")
    return real
def _pick_paths(window,label,ext,staged=None,extra_exts=()):
    return [_staged_path(staged)] if staged else _open_dialog(window,label,ext,extra_exts)
def _open_dialog(window,label,ext,extra_exts=()):
    paths=window.create_file_dialog(webview.FileDialog.OPEN,directory=_dialog_dir(),file_types=(_file_types(label,ext,*extra_exts),))
    if paths:_remember_dialog_dir(os.path.dirname(paths[0]))
    return paths
def _save_dialog(window,label,ext,default):
    directory,name=_dialog_dir(),default
    for _attempt in range(5):
        out=_first_path(window.create_file_dialog(webview.FileDialog.SAVE,directory=directory,save_filename=name,file_types=(_file_types(label,ext),)))
        if not out:return None
        if _IS_LINUX:
            fixed=_with_extension(out,ext)
            if fixed!=out and os.path.exists(fixed) and not window.create_confirmation_dialog("Replace file?",f"\"{os.path.basename(fixed)}\" already exists in {os.path.dirname(fixed)}. Replace it?"):
                directory,name=os.path.dirname(fixed),os.path.basename(fixed)
                continue
            out=fixed
            _remember_dialog_dir(os.path.dirname(out))
        return out
    return None
def save_window_geometry(window,maximized,normal_geometry=None,current_geometry=None):
    try:
        if maximized and normal_geometry:
            x,y,w,h=normal_geometry
        elif current_geometry:
            x,y,w,h=current_geometry
        else:
            x,y,w,h=int(window.x),int(window.y),int(window.width),int(window.height)
        geo={"x":int(x),"y":int(y),"w":int(w),"h":int(h),"maximized":bool(maximized)}
        with _settings_lock.SETTINGS_LOCK:
            d=read_settings();d["window"]=geo
            write_settings(d)
    except Exception:pass
class BridgeModule:
    def __init__(self):
        self._window=None
    def bind(self,window):
        self._window=window
class WindowAPI(BridgeModule):
    def __init__(self):
        super().__init__()
        self._maximized=False
        self._pre_maximize_geo=None
    def bind(self,window,maximized=False,pre_geo=None):
        super().bind(window)
        self._maximized=bool(maximized)
        self._pre_maximize_geo=pre_geo if maximized else None
        self._geo=tuple(int(v) for v in pre_geo) if pre_geo else None
        window.events.maximized+=self._on_maximized
        window.events.restored+=self._on_restored
        window.events.moved+=self._on_moved
        window.events.resized+=self._on_resized
        window.events.closing+=self._on_closing
        if maximized:window.events.shown+=self._maximize_to_work_area
    def _on_maximized(self):
        if _IS_LINUX and not self._maximized:self._pre_maximize_geo=None
        self._maximized=True
    def _on_restored(self):self._maximized=False
    def _on_moved(self,x,y):
        w,h=(self._geo[2],self._geo[3]) if self._geo else (MIN_W,MIN_H)
        self._geo=(int(x),int(y),int(w),int(h))
    def _on_resized(self,width,height):
        x,y=(self._geo[0],self._geo[1]) if self._geo else (0,0)
        self._geo=(int(x),int(y),int(width),int(height))
    def _on_closing(self):
        try:_diag_log.info("[*] Main window close requested")
        except Exception:pass
        save_window_geometry(self._window,self._maximized,self._pre_maximize_geo,self._geo)
        try:_terminal_svc.close_all_sessions()
        except Exception:pass
        try:_mcp_local_svc.stop_server()
        except Exception:pass
        try:_security_svc.encrypt_on_exit()
        except Exception:pass
        if _IS_LINUX:
            mini=_windows.get("mini")
            if mini is not None:_destroy_soon(mini)
    def _restore_native(self):
        _gtk_unmaximize(self._window)
        self._window.restore()
    def _maximize_to_work_area(self):
        x,y,w,h=_work_area_for_window(self._window)
        self._restore_native()
        self._window.resize(w,h)
        self._window.move(x,y)
        self._maximized=True
        return True
    def minimize(self):
        self._window.minimize()
        return True
    def toggle_maximize(self):
        if self._maximized:
            self._restore_native()
            self._maximized=False
            if self._pre_maximize_geo:
                x,y,w,h=self._pre_maximize_geo
                self._window.resize(w,h)
                self._window.move(x,y)
        else:
            self._pre_maximize_geo=(int(self._window.x),int(self._window.y),int(self._window.width),int(self._window.height))
            self._maximize_to_work_area()
        return self._maximized
    def close(self):
        _destroy_soon(self._window)
        return True
    def drag_to(self,x,y):
        if self._maximized:return False
        self._window.move(int(x),int(y))
        return True
    def size(self):
        return {"w":int(self._window.width),"h":int(self._window.height)}
    def bounds(self):
        return {"x":int(self._window.x),"y":int(self._window.y),"w":int(self._window.width),"h":int(self._window.height)}
    def resize_to(self,w,h):
        if self._maximized:return False
        w=max(MIN_W,int(w));h=max(MIN_H,int(h))
        self._window.resize(w,h)
        return True
    def set_bounds(self,x,y,w,h):
        if self._maximized:return False
        w=max(MIN_W,int(w));h=max(MIN_H,int(h))
        self._window.resize(w,h)
        self._window.move(int(x),int(y))
        return {"x":int(x),"y":int(y),"w":w,"h":h}
    def restore_for_drag(self,screen_x,screen_y,ratio):
        if not self._maximized:return None
        _ox,_oy,w,h=self._pre_maximize_geo or (0,0,900,650)
        ratio=min(max(float(ratio),0.0),1.0)
        nx=int(screen_x-(ratio*w))
        ny=max(0,int(screen_y-16))
        self._restore_native()
        self._maximized=False
        self._window.resize(w,h)
        self._window.move(nx,ny)
        return {"x":nx,"y":ny,"w":w,"h":h}
    def is_maximized(self):
        return self._maximized
    def chrome(self):
        """rounded: the window is transparent and the page paints its own rounded corners (Linux with a compositor only)."""
        return {"rounded":bool(_ROUNDED_WINDOWS.get("main")),"maximized":bool(self._maximized)}
    def shrink(self):
        if _security_svc.is_locked():return False
        mini=_windows.get("mini")
        if mini is None:
            mini,_api=create_mini_window()
        else:
            mini.show()
        self._window.hide()
        return True
class ThemeAPI:
    def get(self):
        return {"mode":_tokens.current_mode(),"theme":_tokens.current_theme()}
    def set(self,mode):
        if not _tokens.set_mode(mode):raise ValueError(f"invalid theme mode: {mode}")
        return self.get()
    def toggle(self):
        nxt="light" if _tokens.current_theme()=="dark" else "dark"
        _tokens.set_mode(nxt)
        return self.get()
    def accent(self):
        a,b=_tokens.current_accent()
        return {"a":a,"b":b,"presets":_tokens.ACCENT_PRESETS}
    def set_accent(self,a,b):
        if not _tokens.set_accent(a,b):raise ValueError("Colors must be hex values like #3b82f6.")
        return self.accent()
    def style(self):
        return {"style":_tokens.current_style(),"styles":list(_tokens.STYLES)}
    def set_style(self,style):
        if not _tokens.set_style(style):raise ValueError(f"invalid appearance style: {style}")
        return self.style()
class DashboardAPI(BridgeModule):
    def get_layout(self):
        return _dashboard.get_layout()
    def save_layout(self,cards):
        return _dashboard.save_layout(cards)
    def catalog(self):
        return {"widgets":_dashboard.WIDGET_CATALOG,"sizes":_dashboard.SIZE_PRESETS}
    def stats(self):
        return _dashboard.get_stats()
    def list_layouts(self):
        return _dashboard.list_layouts()
    def save_layout_as(self,name):
        return _dashboard.save_layout_as(name)
    def apply_layout(self,name):
        return _dashboard.apply_layout(name)
    def delete_layout(self,name):
        return _dashboard.delete_layout(name)
    def restore_default(self):
        return _dashboard.restore_default()
    def presets(self):
        return _dashboard.list_presets()
    def apply_preset(self,preset_id):
        return _dashboard.apply_preset(preset_id)
def _notes_clean_cmds(cmds):
    clean_cmds=[]
    for c in (cmds or []):
        if not isinstance(c,dict):continue
        align=_notes_svc._norm(c.get("align",""))
        clean_cmds.append({"cid":_notes_svc._norm(c.get("cid","")),"cmd_note_title":_notes_svc._norm(c.get("cmd_note_title","")),"category":_notes_svc._norm(c.get("category","")),"sub_category":_notes_svc._norm(c.get("sub_category","")),"description":_notes_svc._norm(c.get("description","")),"tags":_notes_svc._norm(c.get("tags","")),"command":(c.get("command","") or "").rstrip(),"align":align if align in ("left","center","right") else "","command_type":_notes_svc._norm(c.get("command_type","")) or "other"})
    return clean_cmds
def _note_id(v):
    # The UI can ask with no selection (null id): answer with a clean message instead of a TypeError from int(None).
    if v is None or isinstance(v,bool) or (isinstance(v,str) and not v.strip()):raise ValueError("No note selected.")
    try:return int(v)
    except (TypeError,ValueError):raise ValueError("No note selected.")
class NotesAPI(BridgeModule):
    def list(self):
        dbp=_notes_svc._db_path()
        notes=_notes_svc._load_notes(dbp)
        pinned_ids=_notes_svc.pinned_note_ids()
        return [{"id":n["id"],"note_name":n["note_name"],"group_name":n["group_name"],"tags":n.get("tags",""),"updated_at":n["updated_at"],"updated_label":_notes_svc._fmt_note_time(n["updated_at"]),"preview":_notes_svc._strip_html(n["content"])[:160],"pinned":n["id"] in pinned_ids} for n in notes]
    def groups(self):
        dbp=_notes_svc._db_path()
        notes=_notes_svc._load_notes(dbp)
        meta=_notes_svc._load_notes_meta()
        rows=_notes_svc.group_rows_data(notes,meta["groups"])
        out=[]
        pinned_ids=_notes_svc.pinned_note_ids()
        if pinned_ids:
            by_id={n["id"]:n for n in notes}
            pinned_notes=[by_id[i] for i in dict.fromkeys(_notes_svc._note_refs.note_ref_id(r) for r in _notes_svc.pinned_refs()) if i in by_id]
            out.append({"group_name":"__pinned__","label":"Pinned","count":len(pinned_notes),"notes":[{"id":n["id"]} for n in pinned_notes]})
        out+=[{"group_name":r["group_name"],"label":r["label"],"count":r["count"],"notes":[{"id":n["id"]} for n in r["notes"]]} for r in rows]
        collapsed=set(_notes_svc.collapsed_group_keys())
        for g in out:g["collapsed"]=(g["group_name"].lower() if g["group_name"] else _notes_svc._NAV_UNGROUPED_KEY) in collapsed
        return out
    def set_group_collapsed(self,group_name,collapsed):
        return _notes_svc.set_group_collapsed(group_name,bool(collapsed))
    def create_group(self,name):
        grp=_notes_svc._norm(name)
        if not grp:raise ValueError("Group name is required.")
        return _notes_svc.ensure_group_meta(grp)
    def rename_group(self,old_group,new_group):
        changed=_notes_svc.rename_group(_notes_svc._db_path(),old_group,new_group)
        _notes_svc.move_group_style(old_group,new_group)
        return changed
    def move_note(self,note_id,group_name):
        return _notes_svc.move_note_to_group(_notes_svc._db_path(),_note_id(note_id),group_name)
    def delete_group(self,group_name):
        ok=_notes_svc.delete_empty_group(_notes_svc._db_path(),group_name)
        if ok:_notes_svc.move_group_style(group_name,"")
        return ok
    # ---- Notes sidebar (left bar): one payload per refresh, preferences in settings.json, content search.
    def _sidebar_targets(self):
        # Read the active profile's Targets.json directly: building a targets Store here would prune and rewrite it on every refresh.
        try:
            d=_notes_svc._read_json(_targets_svc._paths(_targets_svc.active_profile_id())[1])
            return d if isinstance(d,list) else []
        except Exception:return []
    def sidebar(self):
        return _notes_svc.sidebar_data(_notes_svc._db_path(),self._sidebar_targets())
    def sidebar_prefs(self):
        return _notes_svc.sidebar_prefs()
    def set_sidebar_pref(self,key,value):
        return _notes_svc.set_sidebar_pref(key,value)
    def set_group_style(self,group_name,color="",icon=""):
        return _notes_svc.set_group_style(group_name,color,icon)
    def set_groups_collapsed(self,group_names,collapsed):
        return _notes_svc.set_groups_collapsed(group_names,bool(collapsed))
    def reorder_pinned(self,note_ids):
        return _notes_svc.reorder_pinned(note_ids)
    def touch_recent(self,note_id,note_name=""):
        return _notes_svc.touch_recent(_note_id(note_id),note_name)
    def search_content(self,query,limit=300):
        return _notes_svc.search_content(_notes_svc._db_path(),query,limit)
    def editor_prefs(self):
        return _notes_svc.editor_prefs()
    def open_url(self,url):
        # Links in a note must never navigate the app window; web and mail links go to the system browser instead.
        u=_notes_svc._norm(url)
        if not u.lower().startswith(("http://","https://","mailto:")):raise ValueError("Only web and mail links can be opened.")
        import webbrowser
        return bool(webbrowser.open(u))
    def set_editor_pref(self,key,value):
        return _notes_svc.set_editor_pref(key,value)
    def set_pinned(self,note_id,note_name,pinned):
        return _notes_svc.set_pinned(note_id,note_name,bool(pinned))
    def tags(self):
        return _notes_svc.all_tags()
    def graph(self):
        return _notes_svc.note_link_graph()
    def get(self,note_id):
        dbp=_notes_svc._db_path()
        notes=_notes_svc._load_notes(dbp)
        note_id=_note_id(note_id)
        note=next((n for n in notes if int(n["id"])==note_id),None)
        if not note:raise ValueError(f"note not found: {note_id}")
        cmds=_notes_svc._load_note_commands(dbp,note_id=note["id"],note_name=note["note_name"])
        linked=_notes_svc.linked_from_notes(dbp,note,notes)
        return {"id":note["id"],"note_name":note["note_name"],"group_name":note["group_name"],"tags":note.get("tags",""),"created_at":note["created_at"],"updated_at":note["updated_at"],"created_label":_notes_svc._fmt_note_time(note["created_at"]),"updated_label":_notes_svc._fmt_note_time(note["updated_at"]),"content_html":_notes_svc.sanitize_note_html(_notes_svc.render_note_content(note["content"],notes,note["note_name"],cmds)),"commands":cmds,"pinned":note["id"] in _notes_svc.pinned_note_ids(),"linked":[{"id":n["id"],"note_name":n["note_name"],"group_name":n["group_name"],"updated_label":_notes_svc._fmt_note_time(n["updated_at"])} for n in linked]}
    def edit_content(self,note_id):
        dbp=_notes_svc._db_path()
        notes=_notes_svc._load_notes(dbp)
        note_id=_note_id(note_id)
        note=next((n for n in notes if int(n["id"])==note_id),None)
        if not note:raise ValueError(f"note not found: {note_id}")
        # Old formats are converted, commands that only exist in the Commands table become cards, and links are re-resolved, so saving never drops a command.
        content=_notes_svc.upgrade_legacy_content(note["content"],note["note_name"])
        content=_notes_svc.ensure_db_cards(content,_notes_svc._load_note_commands(dbp,note_id=note["id"],note_name=note["note_name"]))
        content=_notes_svc.normalize_note_links(content,notes)
        cmds=_notes_svc.extract_editor_cmd_cards(content,note["note_name"])
        return {"id":note["id"],"note_name":note["note_name"],"group_name":note["group_name"],"tags":note.get("tags",""),"content_html":_notes_svc.sanitize_note_html(_notes_svc.render_editor_content(content,note["note_name"])),"commands":cmds}
    def save(self,note_id,name,group_name,content_html,cmds,tags=""):
        name=_notes_svc._norm(name)
        if not name:raise ValueError("Note name is required.")
        group_name=_notes_svc._norm(group_name);tags=_notes_svc._norm(tags)
        dbp=_notes_svc._db_path()
        # The cmds list only fills the editor's card markers; the Commands rows are rebuilt from the cards in the saved HTML (save_note with cmds=None).
        final_html=_notes_svc.prepare_note_html(_notes_svc.finalize_editor_content(_notes_svc.sanitize_note_html(content_html),_notes_clean_cmds(cmds)),name,dbp)
        if _notes_svc.note_html_is_empty(final_html):raise ValueError("Note area is empty.")
        if note_id:
            final_html=_notes_svc.finalize_attachments(final_html,note_id)
            nid,ncmd,action=_notes_svc.save_note(dbp,note_id,name,group_name,final_html,None,tags)
        else:
            nid,ncmd,action=_notes_svc.save_note(dbp,None,name,group_name,final_html,None,tags)
            moved_html=_notes_svc.finalize_attachments(final_html,nid)
            if moved_html!=final_html:
                _notes_svc.replace_saved_content(dbp,nid,moved_html);final_html=moved_html
        if action!="unchanged":_semantic_svc.index_note(nid,name,_notes_svc._strip_html(final_html))
        _targets_svc.auto_add_target_values()
        return {"id":nid,"action":action,"command_count":ncmd}
    def append(self,note_id,content_html):
        dbp=_notes_svc._db_path()
        notes=_notes_svc._load_notes(dbp)
        note_id=_note_id(note_id)
        note=next((n for n in notes if int(n["id"])==note_id),None)
        if not note:raise ValueError(f"note not found: {note_id}")
        addition=(content_html or "").strip()
        if not addition:raise ValueError("content is required.")
        existing=_notes_svc.ensure_db_cards(_notes_svc.upgrade_legacy_content(note["content"],note["note_name"]),_notes_svc._load_note_commands(dbp,note_id=note["id"],note_name=note["note_name"]))
        # Same write-side sanitising as save(): notes_append is reachable from MCP agents. The whole result is cleaned so a tag left
        # open at the end of the addition cannot pick up attributes from what follows.
        combined=_notes_svc.prepare_note_html(_notes_svc.sanitize_note_html(existing+addition),note["note_name"],dbp)
        nid,ncmd,action=_notes_svc.save_note(dbp,note_id,note["note_name"],note["group_name"],combined,None,note.get("tags",""))
        _semantic_svc.index_note(nid,note["note_name"],_notes_svc._strip_html(combined))
        _targets_svc.auto_add_target_values()
        return {"id":nid,"action":action,"command_count":ncmd}
    def command_block_html(self,cmd_note_title,category,sub_category,command,tags="",description=""):
        command=(command or "").strip()
        if not command:raise ValueError("command is required.")
        data={"cmd_note_title":_notes_svc._norm(cmd_note_title),"category":_notes_svc._norm(category),"sub_category":_notes_svc._norm(sub_category),"description":_notes_svc._norm(description),"tags":_notes_svc._norm(tags),"command":command}
        token=_notes_svc._encode_cmd_data(data)
        return f'<a href="cmd:edit:{token}"><img src="cmdcard:{token}" width="320" height="90" /></a>'
    def versions(self,note_id):
        return _notes_svc.list_versions(note_id)
    def version_diff(self,note_id,version_id):
        return _notes_svc.diff_versions(note_id,version_id)
    def restore_version(self,note_id,version_id):
        return _notes_svc.restore_version(note_id,version_id)
    def insert_attachment(self,filename,data_b64):
        return _notes_svc.save_pending_attachment(filename,data_b64)
    def attachment_data(self,attachment_id):
        return _notes_svc.attachment_data_url(attachment_id)
    def attachment_view(self,attachment_id):
        return _notes_svc.attachment_view(attachment_id)
    def discard_pending_attachments(self,ids):
        _notes_svc.discard_pending_attachments(ids)
        return True
    def attachment_open(self,attachment_id,display_name=""):
        # Only an id goes in: the file is resolved under Data/Attachments, and an encrypted one is opened from a private plain copy.
        return _notes_svc.open_attachment(attachment_id,display_name)
    def attachment_save_as(self,attachment_id,display_name=""):
        name,ext=_notes_svc.attachment_save_default(attachment_id,display_name)
        _notes_svc._attachment_require_unlocked()
        if not self._window:raise ValueError("Save as is not available in this window.")
        if ext:out=_save_dialog(self._window,ext.upper()+" file",ext,name)
        else:
            out=_first_path(self._window.create_file_dialog(webview.FileDialog.SAVE,directory=_dialog_dir(),save_filename=name))
            if out:_remember_dialog_dir(os.path.dirname(out))
        if not out:return None
        return _notes_svc.save_attachment_copy(attachment_id,out,display_name)
    def link_token(self,note_id,note_name):
        return _notes_svc._encode_note_link_data({"note_id":note_id,"note_name":note_name})
    def templates(self):
        return [{"id":t["id"],"name":t["name"]} for t in _notes_svc.list_templates()]
    def save_template(self,name,content_html,cmds):
        clean_cmds=_notes_clean_cmds(cmds)
        final_html=_notes_svc.finalize_editor_content(content_html,clean_cmds)
        return {"id":_notes_svc.save_template(name,final_html)}
    def new_from_template(self,template_id):
        tpl=_notes_svc.get_template(template_id)
        if not tpl:raise ValueError("Template not found.")
        cmds=_notes_svc.extract_editor_cmd_cards(tpl["content_html"])
        return {"content_html":_notes_svc.render_editor_content(tpl["content_html"]),"commands":cmds}
    def delete_template(self,template_id):
        return _notes_svc.delete_template(template_id)
    def delete(self,note_id):
        dbp=_notes_svc._db_path()
        notes=_notes_svc._load_notes(dbp)
        note_id=_note_id(note_id)
        note=next((n for n in notes if int(n["id"])==note_id),None)
        if not note:raise ValueError(f"note not found: {note_id}")
        if not _notes_svc._delete_note(dbp,note["note_name"]):raise ValueError("Delete failed.")
        _semantic_svc.remove_note(note_id)
        _notes_svc.purge_orphan_attachments(dbp)
        return True
    def draft_get(self):
        return _notes_svc.load_draft()
    def draft_save(self,payload):
        _notes_svc.save_draft(payload if isinstance(payload,dict) else {})
        return True
    def draft_clear(self):
        _notes_svc.clear_draft()
        return True
class CommandsAPI:
    # Persisted in settings.json: pywebview runs WebKitGTK in private mode, where localStorage does not exist.
    PAGE_SIZES=(10,20,50,100)
    def get_page_size(self):
        v=read_settings().get("commands_page_size")
        return v if v in self.PAGE_SIZES else 20
    def set_page_size(self,n):
        try:n=int(n)
        except (TypeError,ValueError):raise ValueError("Invalid page size")
        if n not in self.PAGE_SIZES:raise ValueError("Invalid page size")
        from Cores import settings_lock as _sl
        _sl.update_json(_settings_path(),lambda d:d.__setitem__("commands_page_size",n))
        return n
    def list(self):
        _commands_svc._sync_missing_note_cmds(_commands_svc._db_path())
        _dbp,rows=_commands_svc._load_cmds()
        return [{k:v for k,v in r.items() if k!="db"} for r in rows]
    def history(self):
        return _commands_svc._history_from_db(_commands_svc._db_path())
    def stamp(self):
        return _commands_svc.commands_stamp()
    def target_elements(self,prefix="",limit=0):
        return _commands_svc.target_element_rows(None,prefix,limit)
    def create(self,note_name,category,sub_category,command,tags,description,command_type="other",noise_level="normal"):
        note_name,category,sub_category,tags=_commands_svc.normalize_command_fields(note_name,category,sub_category,tags)
        ok,err=_commands_svc.validate_command_fields(note_name,category,sub_category,command)
        if not ok:raise ValueError(err)
        dbp=_commands_svc._db_path()
        nid=_commands_svc._insert_cmd(dbp,note_name.strip(),category.strip(),sub_category.strip(),command,(tags or "").strip(),(description or "").strip(),command_type,noise_level)
        if nid is None:raise ValueError("Insert failed.")
        _semantic_svc.index_command(nid,note_name.strip(),f"{category} / {sub_category}: {command}\n{description}\ntags: {tags}")
        _targets_svc.auto_add_target_values()
        return {"id":nid}
    def update(self,cmd_id,note_name,category,sub_category,command,tags,description,command_type="other",noise_level="normal"):
        note_name,category,sub_category,tags=_commands_svc.normalize_command_fields(note_name,category,sub_category,tags)
        ok,err=_commands_svc.validate_command_fields(note_name,category,sub_category,command)
        if not ok:raise ValueError(err)
        dbp=_commands_svc._db_path()
        ok2=_commands_svc._update_cmd(dbp,cmd_id,note_name.strip(),category.strip(),sub_category.strip(),command,(tags or "").strip(),(description or "").strip(),command_type,noise_level)
        if not ok2:raise ValueError("Command not found.")
        _semantic_svc.index_command(cmd_id,note_name.strip(),f"{category} / {sub_category}: {command}\n{description}\ntags: {tags}")
        _targets_svc.auto_add_target_values()
        return {"id":cmd_id}
    def record_run(self,command_id,src,text,target_snapshot):
        return _commands_svc.log_command_run(command_id,src,text,target_snapshot)
    def runs(self,command_id,src):
        return _commands_svc.list_command_runs(command_id,src)
    def delete(self,cmd_id,src):
        dbp=_commands_svc._db_path()
        ok=_commands_svc._delete_cmd({"db":dbp,"id":cmd_id,"src":src})
        if not ok:raise ValueError("Delete failed - note-linked commands must be removed from the note itself.")
        if src=="CommandsNotes":_semantic_svc.remove_command(cmd_id)
        return True
    def linked_note_count(self,item):
        dbp=_commands_svc._db_path()
        return _commands_svc._linked_note_count(dbp,item)
    def linked_rows(self,item):
        dbp=_commands_svc._db_path()
        return _commands_svc._linked_command_rows(dbp,item)
    def update_linked(self,old_item,new_item):
        new_item=dict(new_item or {})
        t,c,s,g=_commands_svc.normalize_command_fields(new_item.get("cmd_note_title",new_item.get("title","")),new_item.get("category",""),new_item.get("sub_category",new_item.get("sub","")),new_item.get("tags",""))
        new_item.update({"cmd_note_title":t,"category":c,"sub_category":s,"tags":g})
        norm=_commands_svc._cmd_norm_data(new_item)
        ok,err=_commands_svc.validate_command_fields(norm["cmd_note_title"],norm["category"],norm["sub_category"],norm["command"])
        if not ok:raise ValueError(err)
        dbp=_commands_svc._db_path()
        ok2=_commands_svc._update_linked_command(dbp,old_item,new_item)
        if not ok2:raise ValueError("Update failed.")
        _targets_svc.auto_add_target_values()
        return True
class PlaybooksAPI:
    def list(self):
        return _playbooks_svc.list_playbooks()
    def get(self,playbook_id):
        pb=_playbooks_svc.get_playbook(playbook_id)
        if not pb:raise ValueError("Action chain not found.")
        return pb
    def create(self,name,caller=None):
        return {"id":_playbooks_svc.create_playbook(name,caller)}
    def set_caller(self,playbook_id,caller):
        return {"caller":_playbooks_svc.set_caller(playbook_id,caller)}
    def validate_caller(self,caller,playbook_id=None):
        return _playbooks_svc.validate_caller(caller,playbook_id)
    def suggest_caller(self,name,playbook_id=None):
        return _playbooks_svc.suggest_caller(name,playbook_id)
    def callers(self):
        return _playbooks_svc.list_callers()
    def rename(self,playbook_id,name):
        return _playbooks_svc.rename_playbook(playbook_id,name)
    def delete(self,playbook_id):
        _flow_svc.chain_deleted(playbook_id)  # the chain's diagram (ChainGraphs row) goes with it
        return _playbooks_svc.delete_playbook(playbook_id)
    def commands(self,playbook_id):
        return _playbooks_svc.playbook_commands(playbook_id)
    def add_step(self,playbook_id,command_id,command_src):
        return {"step_id":_playbooks_svc.add_step(playbook_id,command_id,command_src)}
    def remove_step(self,step_id):
        return _playbooks_svc.remove_step(step_id)
    def move_step(self,step_id,direction):
        return _playbooks_svc.move_step(step_id,direction)
class TargetsAPI:
    def __init__(self):
        self._store=None
        self._sig=None
    def _get_store(self):
        # Rebuild whenever the profile, its JSON files or the DB changed: Mini, Recycle Bin restores, imports and command saves all write behind this cache.
        active=_targets_svc.active_profile_id()
        sig=_targets_svc.store_signature(active)
        if self._store is None or self._sig!=sig:
            self._store=_targets_svc.Store(active)
            self._sig=_targets_svc.store_signature(active)
        return self._store
    def targets(self):
        return self._get_store().targets
    def list_profiles(self):
        return _targets_svc.list_profiles()
    def create_profile(self,name):
        ok,msg,pid=_targets_svc.create_profile(name)
        if not ok:raise ValueError(msg)
        return _targets_svc.list_profiles()
    def rename_profile(self,pid,name):
        ok,msg=_targets_svc.rename_profile(pid,name)
        if not ok:raise ValueError(msg)
        return _targets_svc.list_profiles()
    def switch_profile(self,pid):
        ok,msg=_targets_svc.switch_profile(pid)
        if not ok:raise ValueError(msg)
        self._store=None
        return _targets_svc.list_profiles()
    def delete_profile(self,pid):
        ok,msg=_targets_svc.delete_profile(pid)
        if not ok:raise ValueError(msg)
        self._store=None
        return _targets_svc.list_profiles()
    def keys(self):
        s=self._get_store()
        dbp=_targets_svc._db_path()
        links=_targets_svc._command_links_map(dbp,include_unlinked=True)
        s.sync_manual_flags(links,save=True)
        last_seen=_targets_svc._command_last_seen_map(dbp,include_unlinked=True)
        _targets_svc._save_last_seen_map(dbp,last_seen)
        items=list(s.values.items())
        items.sort(key=lambda x:(_targets_svc._clamp_u16(_targets_svc._priority_from(x[1])),x[0].lower()))
        out=[]
        for k,v in items:
            lk=_targets_svc._kci(k)
            ls=last_seen.get(lk)
            out.append({"key":k,"priority":_targets_svc._clamp_u16(_targets_svc._priority_from(v)),"manual":_targets_svc._manual_from(v),"links":links.get(lk,0),"last_seen":ls.isoformat() if ls else None})
        return out
    def add_key(self,key,priority):
        ok,msg=self._get_store().add_key(key,priority,True)
        if not ok:raise ValueError(msg)
        return True
    def rename_key(self,old_key,new_key):
        ok,msg=self._get_store().rename_key(old_key,new_key)
        if not ok:raise ValueError(msg)
        return msg
    def set_priority(self,key,priority):
        s=self._get_store()
        found=None
        for k in s.values.keys():
            if _targets_svc._kci(k)==_targets_svc._kci(key):found=k;break
        if not found:raise ValueError("Key not found")
        cur=s.values.get(found,{})
        manual=bool(cur.get("manual",False)) if isinstance(cur,dict) else False
        s.values[found]={"priority":_targets_svc._clamp_u16(priority),"manual":manual}
        if not s.save_values():raise ValueError("Save failed")
        return True
    def bulk_rename(self,old_keys,new_key):
        ok,msg=self._get_store().bulk_rename(old_keys,new_key)
        if not ok:raise ValueError(msg)
        return msg
    def remove_key(self,key):
        ok,msg=self._get_store().remove_key(key)
        if not ok:raise ValueError(msg)
        return True
    def key_usage(self,key):
        dbp=_targets_svc._db_path()
        return _targets_svc._commands_for_key(dbp,key,include_unlinked=True)
    def audit(self):
        return _targets_svc.audit_keys()
    def key_pattern(self):
        return _targets_svc._allow_dots_colons()
    def set_key_pattern(self,val):
        _targets_svc._set_allow_dots_colons(bool(val))
        return True
    def upsert_target(self,tid,name,status,values,engagement_status=None):
        ok,msg=self._get_store().upsert_target(tid,name,status,values,engagement_status)
        if not ok:raise ValueError(msg)
        return self._get_store().targets
    def set_engagement_status(self,tid,status):
        ok,msg=self._get_store().set_target_engagement_status(tid,status)
        if not ok:raise ValueError(msg)
        return self._get_store().targets
    def expand_cidr(self,value):
        return _targets_svc.expand_cidr(value)
    def delete_target(self,tid):
        ok,msg=self._get_store().delete_target(tid)
        if not ok:raise ValueError(msg)
        return True
    def set_live_target(self,tid):
        ok,msg=self._get_store().set_live_target(tid)
        if not ok:raise ValueError(msg)
        return self._get_store().targets
    def set_target_status(self,tid,status):
        ok,msg=self._get_store().set_target_status(tid,status)
        if not ok:raise ValueError(msg)
        return self._get_store().targets
class SearchAPI:
    def __init__(self):
        self._ctx=None
    def _get_ctx(self):
        if self._ctx is None:self._ctx=_search_svc.LiveTargetContext()
        elif self._ctx.changed():self._ctx.reload()
        return self._ctx
    def list(self):
        _commands_svc._sync_missing_note_cmds(_search_svc._db_path())
        _dbp,rows=_search_svc._load_cmds()
        return rows
    def live_target(self):
        ctx=self._get_ctx()
        return {"name":ctx.name,"map":ctx.map}
    def favorites(self):
        favs,only=_search_svc.load_favorites()
        return {"favorites":favs,"favorites_only":only}
    def set_favorites(self,favorites,favorites_only):
        if not _search_svc.save_favorites(favorites,favorites_only):raise ValueError("Save failed.")
        return True
    def related_notes(self,item):
        dbp=_search_svc._db_path()
        return _commands_svc.related_notes(dbp,item)
    def global_search(self,query):
        return _search_svc.global_search(query)
    def recent_queries(self):
        return _search_svc.list_recent_queries()
    def record_recent_query(self,query):
        return _search_svc.record_recent_query(query)
class MiniWindowAPI(BridgeModule):
    def chrome(self):
        return {"rounded":bool(_ROUNDED_WINDOWS.get("mini")),"maximized":False}
    def bind(self,window,geo=None,size=None):
        super().bind(window)
        self._geo=tuple(int(v) for v in geo) if geo else None
        size=size or (geo[2:] if geo else None)
        self._size=(int(size[0]),int(size[1])) if size else None
        self._collapsed=False
        self._allow_close=False;self._quitting=False;self._last_activity=0.0
        window.events.moved+=self._on_moved
        window.events.resized+=self._on_resized
        window.events.closing+=self._on_closing
        main=_windows.get("main")
        if main is not None:main.events.closing+=self._on_main_closing
    def _on_main_closing(self):
        self._allow_close=True
    def _on_moved(self,x,y):
        w,h=(self._geo[2],self._geo[3]) if self._geo else (self._size or (MINI_MIN_W,MINI_MIN_H))
        self._geo=(int(x),int(y),int(w),int(h))
    def _on_resized(self,width,height):
        x,y=(self._geo[0],self._geo[1]) if self._geo else (0,0)
        self._geo=(int(x),int(y),int(width),int(height))
        if not self._collapsed and int(height)>=MINI_MIN_H:self._size=(int(width),int(height))
    def _on_closing(self):
        main=_windows.get("main")
        if not self._allow_close and main is not None:
            # A window-manager close (Alt+F4) would leave the hidden main window running with no UI. Cancel it and quit the way
            # the X button does, so Quick Space is flushed first. Never touch the window from here (GTK deadlock): use a thread.
            if not self._quitting:
                self._quitting=True
                threading.Thread(target=self._quit_from_wm,daemon=True).start()
            return False
        if self._geo or not _IS_LINUX:self._save_geometry()
        _windows.pop("mini",None)
    def _quit_from_wm(self,grace=3.0):
        # The page saves Quick Space and calls close(True); if it cannot (hung page), quit anyway after a grace period.
        def fallback():
            if _windows.get("mini") is self._window:self.close(True)
        t=threading.Timer(grace,fallback);t.daemon=True;t.start()
        try:self._window.run_js("miniCloseApp();0")
        except Exception:pass
    def _geometry_record(self,geo):
        x,y,w,h=geo
        if self._collapsed and self._size:w,h=self._size
        return {"x":int(x),"y":int(y),"w":int(w),"h":max(MINI_MIN_H,int(h))}
    # live=True reads the real window; only call it from a bridge call, never from a window event (GTK deadlock).
    def _save_geometry(self,live=False):
        try:
            if live or not self._geo:
                self._geo=(int(self._window.x),int(self._window.y),int(self._window.width),int(self._window.height))
                if not self._collapsed and self._geo[3]>=MINI_MIN_H:self._size=self._geo[2:]
            _quick_svc._save_mini_settings(self._geometry_record(self._geo))
        except Exception:pass
    def minimize(self):
        self._window.minimize()
        return True
    def close(self,quit_app=True):
        # ORIG MiniWindow.closeEvent saved and quit: with main hidden a bare destroy left an invisible process behind.
        self._allow_close=True
        self._save_geometry(live=True)
        _windows.pop("mini",None)
        main=_windows.get("main")
        _destroy_soon(self._window)
        if main is not None:
            if quit_app:_destroy_soon(main,0.4)
            else:main.show()
        return True
    def drag_to(self,x,y):
        self._window.move(int(x),int(y))
        return True
    def size(self):
        return {"w":int(self._window.width),"h":int(self._window.height)}
    def resize_to(self,w,h):
        w=max(MINI_MIN_W,int(w));h=MINI_COLLAPSED_H if self._collapsed else max(MINI_MIN_H,int(h))
        self._window.resize(w,h)
        return True
    def save_geometry(self):
        self._save_geometry(live=True)
        return True
    def set_collapsed(self,val):
        val=bool(val)
        try:
            w,h=int(self._window.width),int(self._window.height)
            if val:
                if not self._collapsed and h>=MINI_MIN_H:self._size=(w,h)
                self._collapsed=True
                self._window.resize(w,MINI_COLLAPSED_H)
            else:
                self._collapsed=False
                sw,sh=self._size or (w,420)
                self._window.resize(max(MINI_MIN_W,w),max(MINI_MIN_H,sh))
        except Exception:self._collapsed=val
        cfg={"collapsed":val}
        if self._size:cfg.update({"w":int(self._size[0]),"h":int(self._size[1])})
        _quick_svc._save_mini_settings(cfg)
        return val
    def set_on_top(self,val):
        on_top=bool(val)
        try:
            done=False
            if sys.platform.startswith("win"):
                try:
                    from webview.platforms.winforms import BrowserView
                    inst=BrowserView.instances.get(self._window.uid)
                    if inst is not None:
                        import ctypes
                        hwnd=inst.Handle.ToInt32()
                        HWND_TOPMOST=-1;HWND_NOTOPMOST=-2
                        SWP_NOMOVE=0x0002;SWP_NOSIZE=0x0001;SWP_SHOWWINDOW=0x0040
                        ctypes.windll.user32.SetWindowPos(hwnd,HWND_TOPMOST if on_top else HWND_NOTOPMOST,0,0,0,0,SWP_NOMOVE|SWP_NOSIZE|SWP_SHOWWINDOW)
                        done=True
                except Exception:pass
            if not done:self._window.on_top=on_top
        except Exception:pass
        _quick_svc._save_mini_settings({"always_on_top":on_top})
        return on_top
    def restore(self):
        self._save_geometry(live=True)
        main=_windows.get("main")
        if main is not None:main.show()
        self._window.hide()
        return True
    def activity(self):
        # The main window's auto-lock only sees its own input; while it is hidden the user works in Mini, so pass the activity on.
        now=time.time()
        if now-self._last_activity<20:return True
        self._last_activity=now
        main=_windows.get("main")
        if main is None:return False
        try:main.run_js("typeof idleResetActivity==='function'&&idleResetActivity();0")
        except Exception:return False
        return True
    def restore_and_open_note(self,note_id):
        nid=int(note_id)
        main=_windows.get("main")
        if main is None:return False
        self.restore()
        js=f"goToPage('notes').then(()=>notesOpen({nid}));0"
        try:
            if hasattr(main,"run_js"):main.run_js(js)
            else:main.evaluate_js(js)
        except Exception:return False
        return True
class MiniApi:
    def __init__(self):
        self.window=MiniWindowAPI()
        self.theme=ThemeAPI()
        self.notes=NotesAPI()
        self.commands=CommandsAPI()
        self.search=SearchAPI()
        self.security=SecurityAPI()
        _guard_while_locked(self)
    def settings(self):
        return _quick_svc._get_mini_settings()
    def save_settings(self,cfg):
        if not _quick_svc._save_mini_settings(cfg if isinstance(cfg,dict) else {}):raise ValueError("Save failed.")
        return True
    def data_sig(self):
        def st(p):
            try:
                v=os.stat(p);return f"{v.st_mtime_ns}:{v.st_size}"
            except OSError:return ""
        dbp=_targets_svc._db_path() or ""
        pid=_targets_svc.active_profile_id()
        return {"db":st(dbp)+"|"+st(dbp+"-wal"),"targets":pid+"|"+st(_targets_svc._paths(pid)[1])}
    def targets_list(self):
        return _targets_svc.Store().targets
    def set_live_target(self,tid):
        store=_targets_svc.Store()
        ok,msg=store.set_live_target(tid)
        if not ok:raise ValueError(msg)
        return store.targets
    def quick_space_get(self):
        return _quick_svc._read_json(_quick_svc._quick_space_path(),{})
    def quick_space_save(self,html,text,wrap):
        data={"html":html or "","text":text or "","wrap":bool(wrap)}
        if not _quick_svc._write_json(_quick_svc._quick_space_path(),data):raise ValueError("Save failed.")
        return True
    def ping(self):
        return {"pong":True,"ts":time.time()}
class SecurityAPI:
    def status(self):
        cfg=_security_svc.get_security_settings()
        return {"app_lock_enabled":cfg["app_lock_enabled"],"pin_set":_security_svc.pin_is_set(cfg),"enc_enabled":cfg["enc_enabled"],"enc_file_exists":_security_svc.encrypted_file_exists() if cfg["enc_enabled"] else False,"enc_version":cfg.get("enc_version",0),"enc_min_pin":_security_svc.ENC_MIN_PIN,"crypto_available":_security_svc._HAS_CRYPTO,"auto_lock_minutes":cfg["auto_lock_minutes"],"locked":_security_svc.is_locked(),"lockout_seconds":_security_svc.lockout_remaining(cfg=cfg),"audit_expiry":cfg["audit_expiry"]}
    def is_locked(self):
        return _security_svc.is_locked()
    def needs_unlock(self):
        v=_security_svc.needs_unlock()
        try:
            cfg=_security_svc.get_security_settings()
            _diag_log.info(f"[sec-diag] needs_unlock={v} settings_path={_security_svc._settings_path()} app_lock_enabled={cfg.get('app_lock_enabled')} pin_set={_security_svc.pin_is_set(cfg)} enc_enabled={cfg.get('enc_enabled')} enc_version={cfg.get('enc_version')}")
        except Exception as e:
            try:_diag_log.info(f"[sec-diag] needs_unlock={v} (diag logging failed: {e})")
            except Exception:pass
        return v
    def unlock(self,pin):
        ok,msg=_security_svc.unlock(pin)
        if not ok:raise ValueError(msg)
        try:
            rep=_health_check.run_health_check(after_security=True)
            if rep.fatal:raise ValueError(rep.fatal_text())
        except ValueError:raise
        except Exception:pass
        return True
    def set_pin(self,new_pin,current_pin=None):
        ok,msg=_security_svc.set_pin(new_pin,current_pin)
        if not ok:raise ValueError(msg)
        return msg
    def set_app_lock(self,enabled,new_pin=None):
        ok,msg=_security_svc.set_app_lock(enabled,new_pin)
        if not ok:raise ValueError(msg)
        return msg
    def set_encryption(self,enabled,pin=None,new_pin=None):
        ok,msg=_security_svc.set_encryption(enabled,pin,new_pin)
        if not ok:raise ValueError(msg)
        return msg
    def lock(self,reason="manual"):
        return _security_svc.lock_now(reason)
    def set_auto_lock_minutes(self,minutes):
        return _security_svc.set_auto_lock_minutes(minutes)
    def audit_log(self,limit=200):
        return _security_svc.list_audit_events(limit)
    def set_audit_expiry(self,enabled,amount=None,unit=None):
        return _security_svc.set_audit_expiry(enabled,amount,unit)
class BackupAPI(BridgeModule):
    def __init__(self):
        super().__init__()
        self._backup=None
    def _get(self):
        if self._backup is None:self._backup=_settings_svc.Backup()
        return self._backup
    def list(self):
        rows=self._get().list()
        return [{"path":p,"name":os.path.basename(p),"modified":mt,"size":sz} for p,mt,sz in rows]
    def settings(self):
        return _settings_svc._get_backup_settings()
    def save_settings(self,cfg):
        if not _settings_svc._save_backup_settings(cfg or {}):raise ValueError("Save failed.")
        return True
    def pick_offsite_dir(self):
        folder=_folder_dialog(self._window)
        if not folder:return None
        return folder if isinstance(folder,str) else folder[0]
    def password_status(self):
        """Backup password state for the Backup card: remembered in the OS keyring, keyring usable, the minimum length, and
        whether encryption at rest is on (backups then use the PIN-wrapped data key and need no backup password)."""
        from Cores import backup_password as _bp
        try:remembered=bool(_bp.has())
        except Exception:remembered=False
        try:keyring_ok=bool(_bp.available())
        except Exception:keyring_ok=False
        return {"remembered":remembered,"keyring":keyring_ok,"min_len":int(getattr(_bp,"MIN_LEN",8)),"at_rest":bool(_common_db.encryption_configured() and _common_db.session_key() is not None)}
    def check_password(self,password,confirm=None):
        from Cores import backup_password as _bp
        pw=str(password or "")
        err=_bp.check(pw,pw if confirm is None else str(confirm))
        try:strength=_bp.strength(pw)
        except Exception:strength={"score":0,"label":""}
        return {"error":err or "","strength":strength}
    def forget_password(self):
        from Cores import backup_password as _bp
        _bp.forget()
        return True
    def notice(self):
        try:return _settings_svc.get_backup_notice() or ""
        except Exception:return ""
    def clear_notice(self):
        try:_settings_svc.clear_backup_notice()
        except Exception:pass
        return True
    def create(self,password=None,remember=False):
        from Cores import backup_password as _bp
        pw=str(password or "") or None
        if pw:
            err=_bp.check(pw,pw)
            if err:raise ValueError(err)
        out=self._get().create(password=pw,remember=bool(remember))
        res={"path":out,"name":os.path.basename(out)}
        if pw and remember:
            try:kept=bool(_bp.has())
            except Exception:kept=False
            if not kept:res["remember_error"]="The password could not be saved: no OS keyring is available, so automatic backups stay off."
        return res
    def pick_restore(self,staged=None):
        """A backup file from disk (.loyabak, or an old plain .zip) for Restore with nothing selected."""
        paths=_pick_paths(self._window,"Backup","loyabak",staged,extra_exts=("zip",))
        if not paths:return None
        p=paths[0]
        return {"path":_remember_pick(p),"name":os.path.basename(p)}
    def needs_pin(self,path):
        """For an encrypted .loyabak: does it need its own PIN (made under another PIN/key than this session's)?"""
        real=_require_picked(path,[p for p,_mt,_sz in self._get().list()])
        return _update_backup.backup_needs_pin(real)
    def restore(self,path,mode,pin=None,current_pin=None,password=None):
        # A backup from LOYA's own list, or a zip the user just picked (importExport.pick_import_all). pin: only for an encrypted
        # .loyabak made under another PIN (this installation's own backups open with the session key). current_pin: re-wraps such
        # a backup's key under the current PIN, so the restore does not bring the backup's PIN back.
        path=_require_picked(path,[p for p,_mt,_sz in self._get().list()])
        ok,msg=self._get().restore(path,mode,pin=pin,current_pin=current_pin,password=str(password or "") or None)
        if not ok:raise ValueError(msg)
        return msg
    def delete(self,paths):
        ok,bad=self._get().delete(paths or [])
        return {"ok":ok,"bad":bad}
class OnboardingAPI:
    def status(self):
        return _settings_svc.get_onboarding_state()
    def complete(self):
        return _settings_svc.set_onboarding_complete(True)
    def reset(self):
        return _settings_svc.set_onboarding_complete(False)
class FocusModeAPI:
    def get(self):
        return {"enabled":_settings_svc.get_focus_mode_enabled()}
    def set(self,enabled):
        return {"enabled":_settings_svc.set_focus_mode_enabled(enabled)}
class NotificationsAPI:
    def available(self):
        return _os_toast.available()
    def settings(self):
        return _settings_svc.get_notification_settings()
    def save_settings(self,enabled):
        return _settings_svc.set_notification_settings(enabled)
    def send_test(self):
        return _os_toast.send("LOYA NG","This is a test notification.")
class RecycleBinAPI:
    def list(self,entity_type=""):
        return _recycle_bin.list_entries(entity_type=entity_type or "")
    def restore(self,entry_id):
        ok,msg=_recycle_bin.restore_entry(entry_id)
        if not ok:raise ValueError(msg)
        return msg
    def delete(self,entry_id):
        ok,msg=_recycle_bin.delete_entry(entry_id)
        if not ok:raise ValueError(msg)
        return msg
    def _many(self,fn,ids):
        ok=0;failed=[]
        labels={int(r["id"]):r.get("label","") for r in _recycle_bin.list_entries()}
        for i in (ids or []):
            try:good,msg=fn(int(i))
            except Exception as e:good,msg=False,str(e)
            if good:ok+=1
            else:failed.append({"id":i,"label":labels.get(int(i),"") if str(i).lstrip("-").isdigit() else "","error":msg})
        return {"ok":ok,"failed":failed}
    def restore_many(self,ids):
        return self._many(_recycle_bin.restore_entry,ids)
    def delete_many(self,ids):
        return self._many(_recycle_bin.delete_entry,ids)
    def purge_all(self):
        return _recycle_bin.purge_all()
    def purge_expired(self):
        return _recycle_bin.purge_expired()
    def get_retention_days(self):
        return _recycle_bin.get_retention_days()
    def set_retention_days(self,days):
        return _recycle_bin.set_retention_days(days)
class TagsAPI:
    def __init__(self):
        self._tm=None
    def _get(self):
        if self._tm is None:self._tm=_settings_svc.TagManager()
        return self._tm
    def list(self):
        rows=self._get().load_summary()
        colors=_settings_svc.get_tag_colors()
        for r in rows:
            r["color"]=colors.get((r.get("tag") or "").lower(),"")
        return rows
    def rename(self,tags,new_tag,include_linked=False):
        tags=tags or []
        if len(tags)!=1:raise ValueError("Select exactly one tag to rename.")
        new_tag=(new_tag or "").strip()
        if not new_tag:raise ValueError("New tag name is required.")
        if tags[0].strip().lower()==new_tag.lower():raise ValueError("New tag matches the old tag.")
        res=self._get().update_tags("rename",tags,new_tag,include_linked=include_linked)
        _settings_svc.rename_tag_color(tags[0],new_tag)
        return res
    def merge(self,tags,new_tag,include_linked=False):
        tags=tags or []
        if len(tags)<2:raise ValueError("Select two or more tags to merge.")
        new_tag=(new_tag or "").strip()
        if not new_tag:raise ValueError("New tag name is required.")
        res=self._get().update_tags("merge",tags,new_tag,include_linked=include_linked)
        for t in tags:
            _settings_svc.rename_tag_color(t,new_tag)
        return res
    def delete(self,tags,include_linked=False):
        if not tags:raise ValueError("Select at least one tag.")
        res=self._get().update_tags("delete",tags,"",include_linked=include_linked)
        for t in tags:
            _settings_svc.set_tag_color(t,"")
        return res
    def colors(self):
        return _settings_svc.get_tag_colors()
    def set_color(self,tag,color):
        return _settings_svc.set_tag_color(tag,color)
# Files the page may import from: only paths a pick_* call handed out (a dialog choice or a staged drop) in this session, plus
# backups LOYA itself lists. The page must not be able to point an importer or a restore at an arbitrary file on disk.
_PICKED_PATHS=set()
def _remember_pick(path):
    if path:_PICKED_PATHS.add(os.path.realpath(str(path)))
    return path
def _require_picked(path,extra_ok=()):
    real=os.path.realpath(str(path or ""))
    if not path or (real not in _PICKED_PATHS and real not in {os.path.realpath(str(x)) for x in extra_ok}):
        raise ValueError("That file is no longer available. Choose it again.")
    return real
class ImportExportAPI(BridgeModule):
    def _tv(self):return _settings_svc.TargetValues()
    def _tg(self):return _settings_svc.Targets()
    def _ne(self):return _notes_svc.NotesExport()
    def _ce(self):return _commands_svc.CommandsExport()
    def build_report(self,note_ids,fmt,branding=None):
        notes=_report_svc.load_notes_for_report(note_ids)
        if not notes:raise ValueError("Select at least one note.")
        branding=branding or {}
        title=_notes_svc._norm(branding.get("title","")) or "LOYA NG Report"
        fmt_map={"markdown":("md","Markdown"),"html":("html","HTML"),"pdf":("pdf","PDF"),"docx":("docx","Word Document")}
        if fmt not in fmt_map:raise ValueError("Unsupported format.")
        ext,label=fmt_map[fmt]
        default=f"report.{ext}"
        paths=_save_dialog(self._window,label,ext,default)
        if not paths:return None
        out=paths if isinstance(paths,str) else paths[0]
        if fmt=="markdown":
            with open(out,"w",encoding="utf-8") as f:f.write(_report_svc.render_markdown(notes,title))
        elif fmt=="html":
            with open(out,"w",encoding="utf-8") as f:f.write(_report_svc.render_html(notes,title))
        elif fmt=="pdf":
            _report_svc.render_pdf(out,notes,title)
        else:
            logo_path=""
            logo_b64=branding.get("logo_b64","")
            if logo_b64:
                logo_path=_report_svc.save_temp_logo(logo_b64)
            try:
                _report_svc.render_docx(out,notes,title,_notes_svc._norm(branding.get("client_name","")),logo_path,_notes_svc._norm(branding.get("date","")))
            finally:
                if logo_path:
                    try:os.remove(logo_path)
                    except Exception:pass
        return out
    def export_stats_report(self,fmt):
        fmt_map={"json":("json","JSON"),"html":("html","HTML"),"pdf":("pdf","PDF")}
        if fmt not in fmt_map:raise ValueError("Unsupported format.")
        ext,label=fmt_map[fmt]
        stats=_dashboard.get_stats()
        default=f"loya_report_statistics.{ext}"
        paths=_save_dialog(self._window,label,ext,default)
        if not paths:return None
        out=paths if isinstance(paths,str) else paths[0]
        if fmt=="json":
            with open(out,"w",encoding="utf-8") as f:json.dump(stats,f,ensure_ascii=False,indent=2)
        elif fmt=="html":
            with open(out,"w",encoding="utf-8") as f:f.write(_dashboard.build_stats_report_html(stats))
        else:
            _dashboard.build_stats_report_pdf(out,stats)
        return out
    def export_stats_png(self,data_b64):
        data_b64=(data_b64 or "").split(",",1)[-1]
        default="loya_report_statistics.png"
        paths=_save_dialog(self._window,"PNG","png",default)
        if not paths:return None
        out=paths if isinstance(paths,str) else paths[0]
        with open(out,"wb") as f:f.write(base64.b64decode(data_b64))
        return out
    _NOTE_EXPORT_FORMATS={"json":("json","JSON"),"csv":("csv","CSV"),"markdown":("zip","Markdown ZIP"),"json_all":("json","JSON"),"csv_zip":("zip","CSV ZIP"),"db":("db","SQLite DB")}
    _PLAIN_DUMP_FORMATS=("db",)
    def export_needs_pin(self,what,fmt):
        """True when this export writes an unencrypted copy that needs the PIN (encryption at rest on)."""
        return {"needs_pin":bool(what=="notes" and fmt in self._PLAIN_DUMP_FORMATS and _common_db.encryption_configured()),"warning":_security_svc.PLAIN_EXPORT_WARNING}
    def export_notes(self,fmt,pin=None):
        ne=self._ne();rows=ne.load()
        if not rows:raise ValueError("No notes to export.")
        if fmt not in self._NOTE_EXPORT_FORMATS:raise ValueError("Unsupported format.")
        if fmt in self._PLAIN_DUMP_FORMATS:
            # Fail before the save dialog; the service checks (and audits) again when it writes.
            ok,msg=_security_svc.plain_export_allowed(pin,"notes export",log_success=False)
            if not ok:raise ValueError(msg)
        ext,label=self._NOTE_EXPORT_FORMATS[fmt]
        default=f"notes.{ext}" if fmt in ("json","csv","markdown") else f"notes_all_tables.{ext}"
        paths=_save_dialog(self._window,label,ext,default)
        if not paths:return None
        out=paths if isinstance(paths,str) else paths[0]
        if fmt=="json":ne.export_json(out,rows)
        elif fmt=="csv":ne.export_csv(out,rows)
        elif fmt=="markdown":ne.export_markdown_zip(out,rows)
        elif fmt=="json_all":ne.export_json_all(out)
        elif fmt=="csv_zip":ne.export_csv_zip(out)
        else:ne.export_db(out,pin=pin)
        return out
    def _parse_notes_incoming(self,ne,fmt,path):
        if fmt=="json":return ne.parse_json(path)
        if fmt=="csv":return ne.parse_csv(path)
        if fmt=="db":return ne.parse_db(path)
        if fmt=="csv_zip":return ne.parse_csv_zip(path)
        if fmt=="markdown_folder":return ne.parse_markdown_folder(path)
        if fmt=="cherrytree":return ne.parse_cherrytree(path)
        raise ValueError("Unsupported format.")
    def pick_notes_import(self,fmt,staged=None):
        ne=self._ne()
        if fmt=="markdown_folder":
            if staged:raise ValueError("Markdown folder imports need a folder - use Choose Folder instead of dropping a file.")
            folder=_folder_dialog(self._window)
            if not folder:return None
            p=folder if isinstance(folder,str) else folder[0]
        else:
            label,ext={"cherrytree":("CherryTree","ctd"),"json":("JSON","json"),"csv":("CSV","csv"),"db":("SQLite DB","db"),"csv_zip":("CSV ZIP","zip")}.get(fmt,("",""))
            if not ext:raise ValueError("Unsupported format.")
            paths=_pick_paths(self._window,label,ext,staged)
            if not paths:return None
            p=paths[0]
        try:incoming=self._parse_notes_incoming(ne,fmt,p)
        except ValueError:raise
        except Exception as e:raise ValueError(f"Failed to read: {e}")
        if not incoming and not ne.commands:raise ValueError("No notes found to import.")
        plan=ne.build_plan(incoming,ne.load())
        return {"plan":plan,"path":_remember_pick(p)}
    def apply_notes_import(self,path,fmt,decisions):
        path=_require_picked(path)
        ne=self._ne()
        incoming=self._parse_notes_incoming(ne,fmt,path)
        plan=ne.build_plan(incoming,ne.load())
        return ne.apply_plan(plan,{int(k):v for k,v in (decisions or {}).items()})
    def export_commands(self,fmt):
        ce=self._ce();rows=ce.load()
        if not rows:raise ValueError("No commands to export.")
        ext="json" if fmt=="json" else "csv"
        default=f"commands.{ext}"
        paths=_save_dialog(self._window,"JSON" if fmt=="json" else "CSV",ext,default)
        if not paths:return None
        out=paths if isinstance(paths,str) else paths[0]
        (ce.export_json if fmt=="json" else ce.export_csv)(out,rows)
        return out
    def pick_commands_import(self,fmt,staged=None):
        ext="json" if fmt=="json" else "csv"
        paths=_pick_paths(self._window,"JSON" if fmt=="json" else "CSV",ext,staged)
        if not paths:return None
        p=paths[0]
        ce=self._ce()
        try:incoming=ce.parse_json(p) if fmt=="json" else ce.parse_csv(p)
        except Exception as e:raise ValueError(f"Failed to read file: {e}")
        if not incoming:raise ValueError("No commands found to import."+(f" {ce.invalid} row(s) had no command text." if ce.invalid else ""))
        plan=ce.build_plan(incoming,ce.load())
        return {"plan":plan,"path":_remember_pick(p)}
    def apply_commands_import(self,path,fmt,decisions):
        path=_require_picked(path)
        ce=self._ce()
        incoming=ce.parse_json(path) if fmt=="json" else ce.parse_csv(path)
        plan=ce.build_plan(incoming,ce.load())
        return ce.apply_plan(plan,{int(k):v for k,v in (decisions or {}).items()})
    def export_target_values(self,fmt):
        tv=self._tv();data=tv.load()
        if not data:raise ValueError("No target values to export.")
        ext="json" if fmt=="json" else "csv"
        default=f"target_values.{ext}"
        paths=_save_dialog(self._window,"JSON" if fmt=="json" else "CSV",ext,default)
        if not paths:return None
        out=paths if isinstance(paths,str) else paths[0]
        (tv.export_json if fmt=="json" else tv.export_csv)(out,data)
        return out
    def pick_target_values_import(self,fmt,staged=None):
        ext="json" if fmt=="json" else "csv"
        paths=_pick_paths(self._window,"JSON" if fmt=="json" else "CSV",ext,staged)
        if not paths:return None
        p=paths[0]
        tv=self._tv()
        try:incoming=tv.parse_json(p) if fmt=="json" else tv.parse_csv(p)
        except Exception as e:raise ValueError(f"Failed to read file: {e}")
        plan=tv.build_plan(incoming,tv.load())
        return {"plan":plan,"path":_remember_pick(p)}
    def apply_target_values_import(self,path,fmt,decisions):
        path=_require_picked(path)
        tv=self._tv()
        incoming=tv.parse_json(path) if fmt=="json" else tv.parse_csv(path)
        base=tv.load()
        plan=tv.build_plan(incoming,base)
        res=tv.apply_plan(base,plan,{int(k):v for k,v in (decisions or {}).items()})
        if not tv.save(base):raise ValueError("Save failed.")
        return res
    def export_targets(self,fmt):
        tg=self._tg();data=tg.load()
        if not data:raise ValueError("No targets to export.")
        ext="json" if fmt=="json" else "csv"
        default=f"targets.{ext}"
        paths=_save_dialog(self._window,"JSON" if fmt=="json" else "CSV",ext,default)
        if not paths:return None
        out=paths if isinstance(paths,str) else paths[0]
        (tg.export_json if fmt=="json" else tg.export_csv)(out,data)
        return out
    def pick_targets_import(self,fmt,staged=None):
        ext="json" if fmt=="json" else "csv"
        paths=_pick_paths(self._window,"JSON" if fmt=="json" else "CSV",ext,staged)
        if not paths:return None
        p=paths[0]
        tg=self._tg()
        try:incoming=tg.parse_json(p) if fmt=="json" else tg.parse_csv(p)
        except Exception as e:raise ValueError(f"Failed to read file: {e}")
        plan=tg.build_plan(incoming,tg.load())
        return {"plan":plan,"path":_remember_pick(p)}
    def apply_targets_import(self,path,fmt,decisions):
        path=_require_picked(path)
        tg=self._tg()
        incoming=tg.parse_json(path) if fmt=="json" else tg.parse_csv(path)
        base=tg.load()
        plan=tg.build_plan(incoming,base)
        base,res=tg.apply_plan(base,plan,{int(k):v for k,v in (decisions or {}).items()})
        if not tg.save(base):raise ValueError("Save failed.")
        return res
    # ---- Export my work / import it (Cores/Services/work_export.py, work_import.py). Imported lazily: the page still loads when
    # one of them fails to import, and only this card reports the error.
    def export_all_info(self):
        """What the export dialog needs before it opens: is encryption at rest on (a plain export then needs the PIN), and the
        password rule for a protected export."""
        from Cores import backup_password as _bp
        return {"at_rest":bool(_common_db.encryption_configured()),"min_len":int(getattr(_bp,"MIN_LEN",8)),"warning":_security_svc.PLAIN_EXPORT_WARNING}
    def export_all(self,opts=None):
        from Cores.Services import work_export as _wx
        opts=opts if isinstance(opts,dict) else {}
        password=str(opts.get("password") or "") or None
        if password:
            from Cores import backup_password as _bp
            err=_bp.check(password,str(opts.get("confirm") if opts.get("confirm") is not None else password))
            if err:raise ValueError(err)
        pin=str(opts.get("pin") or "") or None
        if not password and _common_db.encryption_configured():
            # Fail before the save dialog; the service checks (and audits) again when it writes.
            ok,msg=_security_svc.plain_export_allowed(pin,"work export",log_success=False)
            if not ok:raise ValueError(msg)
        ext="loyawork" if password else "zip"
        paths=_save_dialog(self._window,"LOYA work export" if password else "ZIP",ext,f"LOYA_Work_export_{time.strftime('%Y%m%d_%H%M%S')}.{ext}")
        if not paths:return None
        out=paths if isinstance(paths,str) else paths[0]
        res=_wx.export_work_zip(out,include_settings=bool(opts.get("include_settings")),include_run_history=opts.get("include_run_history",True) is not False,
                                include_ai_chats=bool(opts.get("include_ai_chats")),password=password,pin=pin)
        res=dict(res or {})
        res.setdefault("path",out);res.setdefault("name",os.path.basename(out))
        return res
    def pick_import_all(self,staged=None):
        from Cores.Services import work_import as _wi
        paths=_pick_paths(self._window,"LOYA export","zip",staged,extra_exts=("loyawork","loyabak"))
        if not paths:return None
        p=paths[0]
        try:kind=_wi.detect(p)
        except Exception as e:raise ValueError(f"Invalid file: {e}")
        if kind=="backup":raise ValueError("This is a full backup of an install. Restore it from Settings > Backup instead.")
        if not kind:raise ValueError("This file is not a LOYA work export.")
        return {"path":_remember_pick(p),"name":os.path.basename(p),"kind":kind,"protected":kind=="work_protected"}
    def preview_import_all(self,path,password=None,pin=None):
        from Cores.Services import work_import as _wi
        path=_require_picked(path)
        return _wi.preview(path,password=str(password or "") or None,pin=str(pin or "") or None)
    def stage_upload(self,name,b64):
        return {"path":_stage_upload(name,b64),"name":os.path.basename(str(name or ""))}
    def sniff_upload(self,staged):
        """Best guess of what a staged file is, so the import dialog can preselect it."""
        p=_staged_path(staged);low=p.lower()
        if low.endswith((".zip",".loyawork")):
            try:
                from Cores.Services import work_import as _wi
                kind=_wi.detect(p)
            except Exception:kind=""
            return {"what":"all" if kind in ("work","work_protected","legacy") else "notes","format":"" if kind else "csv_zip"}
        return {"what":"","format":""}
    def import_needs_pin(self,path):
        return _update_backup.backup_needs_pin(_require_picked(path))
    def apply_import_all(self,path,opts=None,pin=None,current_pin=None):
        """opts: {mode: merge|replace, clash: rename|skip, password, apply_settings, pin}. A bare mode string (older pages) is
        read as {mode}."""
        path=_require_picked(path)
        from Cores.Services import work_import as _wi
        if not isinstance(opts,dict):opts={"mode":opts,"pin":pin}
        mode=str(opts.get("mode") or "merge")
        if mode not in ("merge","replace"):raise ValueError("Invalid mode.")
        clash=str(opts.get("clash") or "rename")
        if clash not in ("rename","skip"):raise ValueError("Invalid clash choice.")
        return _wi.apply(path,mode=mode,clash=clash,password=str(opts.get("password") or "") or None,apply_settings=bool(opts.get("apply_settings")),pin=str(opts.get("pin") or "") or None)
class TemplatesAPI(BridgeModule):
    _HUMAN_EXT={"md":("Markdown","md"),"json":("JSON","json"),"csv":("CSV","csv")}
    def export_human(self,kind,fmt):
        text=_templates_svc.human_template_text(kind,fmt)
        if not text:raise ValueError("Template is not available.")
        label,ext=self._HUMAN_EXT.get(fmt,("Text","txt"))
        default=f"{kind.title().replace('_','')}_Template.{ext}"
        paths=_save_dialog(self._window,label,ext,default)
        if not paths:return None
        out=paths if isinstance(paths,str) else paths[0]
        with open(out,"w",encoding="utf-8") as f:f.write(text if text.endswith("\n") else text+"\n")
        return out
    def export_ai(self,kind):
        text=_templates_svc.ai_template_text(kind)
        if not text:raise ValueError("Template is not available.")
        default=f"LOYA_{kind.title().replace('_','')}_AI_Template.md"
        paths=_save_dialog(self._window,"Markdown","md",default)
        if not paths:return None
        out=paths if isinstance(paths,str) else paths[0]
        with open(out,"w",encoding="utf-8") as f:f.write(text if text.endswith("\n") else text+"\n")
        return out
    def export_human_bundle(self):
        paths=_save_dialog(self._window,"ZIP","zip","LOYA_Human_Templates.zip")
        if not paths:return None
        out=paths if isinstance(paths,str) else paths[0]
        _templates_svc.write_human_bundle(out)
        return out
    def export_ai_bundle(self):
        paths=_save_dialog(self._window,"ZIP","zip","LOYA_AI_Templates.zip")
        if not paths:return None
        out=paths if isinstance(paths,str) else paths[0]
        _templates_svc.write_ai_bundle(out)
        return out
# Identifies this app run, so "Remind me later" lasts until the next launch (or the reminder time, whichever is first).
_UPDATE_SESSION_ID=f"{os.getpid()}-{int(time.time())}"
class _UpdateJob:
    """One background "Update now" run (download -> verify -> backup -> hand off to the helper) the UI polls for progress."""
    def __init__(self):
        self.lock=threading.Lock()
        self.thread=None
        self.cancel=threading.Event()
        self.reset()
    def reset(self):
        self.state={"running":False,"stage":"idle","percent":0,"message":"","error":"","error_kind":"","target_version":"","done":False,"ready_to_restart":False}
    def snapshot(self):
        with self.lock:return dict(self.state)
    def set(self,**kw):
        with self.lock:self.state.update(kw)
_UPDATE_JOB=_UpdateJob()
def _quit_for_update():
    # Closing the main window runs its normal shutdown (geometry, terminals, encrypt-on-exit) and takes the Mini window with it.
    main=_windows.get("main") or (webview.windows[0] if webview.windows else None)
    if main is not None:_destroy_soon(main,0.4)
class UpdateAPI:
    def _status_text(self,state):
        st=state if isinstance(state,dict) else {}
        cur=str(st.get("current_version","") or "").strip()
        latest=str(st.get("last_available_version","") or "").strip()
        pending=str(st.get("pending_version","") or "").strip()
        err=str(st.get("last_error","") or "").strip()
        staged=str(st.get("staged_version","") or "").strip()
        if st.get("update_in_progress"):
            if pending and cur and pending==cur:return f"Installed update {pending}. Waiting for first successful launch confirmation."
            return f"Update in progress to {pending or latest or '?'}."
        if err:return "Error: "+err
        if staged and staged==latest:return f"Update {staged} is downloaded and verified; it installs the next time LOYA NG starts."
        if pending:return f"Pending update detected for {pending}."
        if cur and latest:
            try:
                cmpv=_update_helpers.compare_semver(latest,cur)
                if cmpv>0:return f"New version available: {latest}."
                if cmpv==0:return "You are on the latest version."
            except Exception:pass
        if latest:return f"Latest authenticated release: {latest}."
        return "Not checked yet."
    def status(self):
        state=_update_svc.get_update_state()
        ident=_update_svc.get_app_identity()
        cfg=_update_svc.get_update_settings()
        snaps=_update_backup.list_code_snapshots()
        cur=str(state.get("current_version","") or "")
        latest=str(state.get("last_available_version","") or "")
        can_update=False
        if cur and latest:
            try:can_update=_update_helpers.compare_semver(latest,cur)>0
            except Exception:can_update=False
        return {"current_version":ident.get("version","") or "-","latest_version":latest or "-","last_checked":state.get("last_checked","") or cfg.get("last_checked","") or "-","last_good_version":state.get("last_good_version","") or "-","source_repo":state.get("source_repo","") or _update_helpers.OFFICIAL_SOURCE_REPO,"manifest_url":_update_helpers.GITHUB_RELEASES_API_URL,"status_text":self._status_text(state),"snapshot_count":len(snaps),"snapshot_dir":str(_update_backup.old_versions_dir()),"can_update":can_update and not bool(state.get("update_in_progress")),"update_in_progress":bool(state.get("update_in_progress")),"release_url":state.get("release_html_url","") or "","staged_version":state.get("staged_version","") or "","settings":cfg}
    def settings(self):
        return _update_svc.get_update_settings()
    def save_settings(self,cfg):
        cfg=cfg if isinstance(cfg,dict) else {}
        allowed={k:cfg[k] for k in ("auto_enabled","check_interval_hours","last_channel","on_available") if k in cfg}
        if not _update_svc.save_update_settings(allowed):raise ValueError("Save failed.")
        return True
    def check_now(self):
        out=_update_svc.check_for_updates(timeout=10)
        try:_update_svc.sync_update_settings_from_state(out.get("state"))
        except Exception:pass
        if not out.get("ok"):raise ValueError("Update check failed: "+str(out.get("error","Unknown error")))
        return {"update_available":bool(out.get("update_available")),"status":self.status()}
    # ----- launch notification -----
    def notice(self):
        if _common_db.is_locked():return {"show":False,"popup":False,"reason":"locked"}
        return _update_svc.update_notice(session_id=_UPDATE_SESSION_ID)
    def remind_later(self,version):
        return {"until":_update_svc.remind_later(str(version or ""),session_id=_UPDATE_SESSION_ID)}
    def skip_version(self,version):
        return {"skipped":_update_svc.skip_version(str(version or ""))}
    def ack_result(self):
        return _update_svc.acknowledge_update_result()
    def open_release_page(self):
        st=_update_svc.get_update_state()
        url=str(st.get("release_html_url","") or "")
        if not _update_helpers.is_official_release_page(url):url=_update_helpers.OFFICIAL_SOURCE_REPO+"/releases"
        import webbrowser
        return bool(webbrowser.open(url))
    def launch_ready(self):
        # Open while locked: the UI calls this as soon as it has loaded, so an installed update is confirmed (or rolled back) before the PIN.
        try:return _update_svc.confirm_launch_health()
        except Exception as e:return {"completed":False,"error":str(e)}
    # ----- Update now (background job with progress) -----
    def _ensure_can_start(self):
        if _common_db.is_locked():raise ValueError("Unlock LOYA NG before updating.")
        state=_update_svc.get_update_state()
        if state.get("update_in_progress"):raise ValueError("An update is already in progress. Let it relaunch or recover first.")
        return state
    def start_update(self):
        self._ensure_can_start()
        job=_UPDATE_JOB
        with job.lock:
            if job.state.get("running"):return dict(job.state)
            job.cancel=threading.Event()
            job.reset()
            job.state.update({"running":True,"stage":"download","percent":1,"message":"Starting ..."})
        def progress(pct,msg):
            job.set(percent=int(pct),message=str(msg))
        def run():
            try:
                py,script=_update_svc.default_launcher()
                out=_update_svc.start_update_install(timeout=60,parent_pid=os.getpid(),launcher_python=py,launcher_script=script,progress=progress,cancel=job.cancel)
                if not out.get("ok"):
                    job.set(running=False,done=True,stage="error",error=str(out.get("error") or "Update failed."),error_kind=str(out.get("error_kind") or ""))
                    return
                man=out.get("manifest") or {}
                job.set(running=False,done=True,stage="ready",percent=100,ready_to_restart=True,target_version=man.get("version",""),message="Restarting LOYA NG to finish the update ...")
                # The helper is already waiting for this process to exit; close on our own so the update never stalls on the UI.
                time.sleep(2.5)
                _quit_for_update()
            except Exception as e:
                job.set(running=False,done=True,stage="error",error=str(e))
        job.thread=threading.Thread(target=run,name="loya-update",daemon=True)
        job.thread.start()
        return job.snapshot()
    def progress(self):
        return _UPDATE_JOB.snapshot()
    def cancel_update(self):
        snap=_UPDATE_JOB.snapshot()
        if snap.get("running") and snap.get("percent",0)<64:
            _UPDATE_JOB.cancel.set()
            return True
        return False
    def restart_to_apply(self):
        snap=_UPDATE_JOB.snapshot()
        if not snap.get("ready_to_restart"):raise ValueError("No update is ready to install.")
        _quit_for_update()
        return True
    def update_now(self):
        # Kept for older callers: runs the whole flow synchronously.
        state=self._ensure_can_start()
        cur=str(state.get("current_version","") or "")
        py,script=_update_svc.default_launcher()
        out=_update_svc.start_update_install(timeout=60,parent_pid=os.getpid(),launcher_python=py,launcher_script=script)
        if not out.get("ok"):raise ValueError("Update start failed: "+str(out.get("error","Unknown error")))
        backups=out.get("backups",{}) if isinstance(out.get("backups",{}),dict) else {}
        manifest=out.get("manifest",{}) if isinstance(out.get("manifest",{}),dict) else {}
        return {"current_version":cur,"target_version":manifest.get("version",""),"data_backup":backups.get("data_backup",""),"code_snapshot":backups.get("code_snapshot",""),"helper_pid":out.get("helper_pid",0)}
    def _open_path(self,p):
        p=str(p or "").strip()
        if not p:return False
        try:
            if os.name=="nt":os.startfile(p)
            else:
                ok,msg=_recovery.open_with_desktop(p)
                if not ok:raise ValueError(msg)
            return True
        except Exception as e:
            raise ValueError(f"Open failed: {e}")
    def open_logs(self):
        p=os.path.join(_health_check.logs_dir(),"Update_log.log")
        try:
            os.makedirs(os.path.dirname(p),exist_ok=True)
            if not os.path.isfile(p):
                with open(p,"a",encoding="utf-8"):pass
        except Exception:pass
        return self._open_path(p)
    def open_snapshots(self):
        p=_update_backup.old_versions_dir()
        os.makedirs(p,exist_ok=True)
        return self._open_path(p)
class TerminalAPI(BridgeModule):
    def shells(self):
        return _terminal_svc.list_shells()
    def shell_extras(self):
        return _terminal_svc.shell_extras()
    def set_default_shell(self,value):
        return _terminal_svc.set_default_shell(value)
    def create_task(self,task,params=None,cols=0,rows=0):
        return _terminal_svc.create_task_session(task,params,cols,rows)
    def create(self,shell_id=None,profile_id=None,cols=0,rows=0,cwd="",startup="",label="",emulator=False):
        return _terminal_svc.create_session(shell_id,profile_id,cols,rows,cwd,startup,label,emulator)
    def set_raw(self,session_id,on):
        return _terminal_svc.set_session_raw(session_id,on)
    def poll(self,session_ids,alive_ids=None):
        return _terminal_svc.poll_sessions(session_ids,alive_ids)
    def cwd(self,session_id):
        return _terminal_svc.session_cwd(session_id)
    def rename(self,session_id,label):
        return _terminal_svc.set_session_label(session_id,label)
    def sessions_state(self):
        return _terminal_svc.sessions_state()
    def saved_save(self,entry):
        return _terminal_svc.save_saved_session(entry)
    def saved_delete(self,entry_id):
        return _terminal_svc.delete_saved_session(entry_id)
    def closed_remember(self,session_id,entry):
        return _terminal_svc.remember_closed_session(session_id,entry)
    def closed_pop(self,entry_id=None):
        return _terminal_svc.pop_closed_session(entry_id)
    def closed_forget(self,entry_id=None):
        return _terminal_svc.forget_closed_session(entry_id)
    def set_remember_output(self,enabled):
        return _terminal_svc.set_remember_output(enabled)
    def workspace_set(self,workspace):
        return _terminal_svc.set_workspace(workspace)
    def write(self,session_id,data):
        return _terminal_svc.write_input(session_id,data)
    def read(self,session_id):
        return _terminal_svc.read_output(session_id)
    def resize(self,session_id,cols,rows):
        return _terminal_svc.resize_session(session_id,cols,rows)
    def alive(self,session_id):
        return _terminal_svc.session_alive(session_id)
    def exit_code(self,session_id):
        return _terminal_svc.session_exit_code(session_id)
    def close(self,session_id):
        return _terminal_svc.close_session(session_id)
    def elevation_info(self):
        return _terminal_svc.elevation_available()
    def launch_elevated(self,shell_id=None):
        ok,result=_terminal_svc.launch_elevated(shell_id)
        if not ok:raise ValueError(result)
        return result
    def get_settings(self):
        return _terminal_svc.get_settings()
    def set_enabled(self,enabled):
        return _terminal_svc.set_enabled(enabled)
    def set_panel_width(self,width):
        return _terminal_svc.set_panel_width(width)
    def set_panel_layout(self,values):
        return _terminal_svc.set_panel_layout(values)
    def batch_output_info(self,job_key):
        return _terminal_svc.batch_output_info(job_key)
    def ai_requests(self,pending_only=False):
        return _terminal_svc.list_ai_requests(pending_only)
    def ai_request_resolve(self,request_id,approved):
        return _terminal_svc.resolve_ai_request(request_id,approved)
    def ai_request_status(self,request_id):
        return _terminal_svc.ai_request_status(request_id)
    def chain_start(self,shell_id,items,policy="stop",source="playbook",chain_name=""):
        return _terminal_svc.start_chain(shell_id,items,policy,source,chain_name)
    def chain_status(self,chain_id):
        return _terminal_svc.chain_status(chain_id)
    def chain_cancel(self,chain_id):
        return _terminal_svc.cancel_chain(chain_id)
    def set_run_behaviour(self,values):
        return _terminal_svc.set_run_behaviour(values)
    def set_shortcuts(self,values):
        return _terminal_svc.set_shortcuts(values)
    def command_index(self,known_sig=None):
        return _terminal_svc.command_index(known_sig)
    def job_start(self,job_key,session_id,command,source="terminal"):
        return _terminal_svc.start_job(job_key,session_id,command,source)
    def job_finish(self,job_key,exit_code=None,cwd="",bytes_out=0,state=""):
        return _terminal_svc.finish_job(job_key,exit_code,cwd,bytes_out,state)
    def job_mark(self,job_key,state):
        return _terminal_svc.mark_job(job_key,state)
    def jobs_list(self,session_id=None,limit=200):
        return _terminal_svc.list_jobs(session_id,limit)
    def job_get(self,job_key):
        return _terminal_svc.get_job(job_key)
    def job_delete(self,job_key):
        return _terminal_svc.delete_job(job_key)
    def jobs_clear_finished(self,session_id=None):
        return _terminal_svc.clear_finished_jobs(session_id)
    def job_interrupt(self,session_id):
        return _terminal_svc.interrupt_session(session_id)
    def jobs_reap(self):
        return _terminal_svc.reap_running_jobs()
    def batch_start(self,shell_id,items,max_concurrent=None,source="batch"):
        return _terminal_svc.start_batch(shell_id,items,max_concurrent,source)
    def batch_output(self,job_key,full=False):
        return _terminal_svc.batch_output(job_key,full)
    def batch_cancel(self,job_key):
        return _terminal_svc.cancel_batch_job(job_key)
    def batch_clear_output(self,job_key=None):
        return _terminal_svc.clear_batch_output(job_key)
    def profiles(self):
        return _terminal_svc.list_profiles()
    def profile_save(self,profile):
        return _terminal_svc.save_profile(profile)
    def profile_delete(self,profile_id):
        return _terminal_svc.delete_profile(profile_id)
    def redact(self,text):
        safe,found=_terminal_svc.redact_secrets(text)
        return {"text":safe,"found":found}
    def export_html(self,title,body_html):
        default="terminal-session.html"
        paths=_save_dialog(self._window,"HTML","html",default)
        if not paths:return None
        out=paths if isinstance(paths,str) else paths[0]
        with open(out,"w",encoding="utf-8") as f:
            f.write(_terminal_svc.render_export_html(title,body_html))
        return out
    def save_output_to_file(self,text):
        default="terminal-session.txt"
        paths=_save_dialog(self._window,"Text","txt",default)
        if not paths:return None
        out=paths if isinstance(paths,str) else paths[0]
        with open(out,"w",encoding="utf-8") as f:
            f.write(text or "")
        return out
class AIAPI:
    def get_settings(self):
        return _ai_svc.get_settings()
    def set_enabled(self,enabled):
        return _ai_svc.set_enabled(enabled)
    def set_panel_width(self,width):
        return _ai_svc.set_panel_width(width)
    def set_panel_layout(self,values):
        return _ai_svc.set_panel_layout(values)
    def providers(self):
        return _ai_svc.get_providers_masked()
    def set_provider(self,kind,cfg):
        return _ai_svc.set_provider(kind,cfg)
    def test_provider(self,kind):
        if kind=="api":return _ai_svc.status_api()
        if kind=="ollama":return _ai_svc.status_ollama()
        if kind=="lmstudio":return _ai_svc.status_lmstudio()
        if kind=="mcp":return _ai_svc.status_mcp()
        raise ValueError(f"Unknown provider type: {kind}")
    def detect_all(self):
        return _ai_svc.detect_all()
    def list_models(self,kind):
        return _ai_svc.list_models(kind)
    def ollama_suggested_models(self):
        return _ai_svc.suggested_ollama_models()
    def ollama_pull_start(self,model_name):
        return _ai_svc.start_pull_ollama_model(model_name)
    def ollama_pull_poll(self,pull_id):
        return _ai_svc.poll_pull_ollama_model(pull_id)
    def mcp_local_status(self):
        return _mcp_local_svc.status()
    def mcp_local_start(self,port=None):
        return _mcp_local_svc.start_server(port)
    def mcp_local_stop(self):
        return _mcp_local_svc.stop_server()
    def enabled_providers(self):
        return _ai_svc.enabled_providers()
    def provider_catalog(self):
        return _ai_svc.provider_catalog()
    def get_default(self):
        return _ai_svc.get_default_provider()
    def set_default(self,kind):
        return _ai_svc.set_default_provider(kind)
    def chat_send(self,session_id,provider_kind,text):
        if not session_id:
            entry=_ai_sessions_svc.create_session(provider_kind)
            session_id=entry["id"]
        session=_ai_sessions_svc.load_session(session_id)
        if session is None:
            entry=_ai_sessions_svc.create_session(provider_kind)
            session_id=entry["id"]
            session=_ai_sessions_svc.load_session(session_id)
        history=session.get("messages") or []
        history=_ai_chat_svc.send_message(provider_kind,history,text)
        _ai_sessions_svc.save_session_messages(session_id,history,provider_kind)
        return {"session_id":session_id,"history":history}
    def chat_send_stream_start(self,session_id,provider_kind,text,attachments=None,display=None):
        if not session_id:
            entry=_ai_sessions_svc.create_session(provider_kind)
            session_id=entry["id"]
        session=_ai_sessions_svc.load_session(session_id)
        if session is None:
            entry=_ai_sessions_svc.create_session(provider_kind)
            session_id=entry["id"]
            session=_ai_sessions_svc.load_session(session_id)
        history=session.get("messages") or []
        refs=[a for a in (attachments or []) if isinstance(a,dict)]
        meta=None
        if refs or display:
            meta={"display":str(display if display else text or "").strip(),"attachments":[{"kind":str(a.get("kind","")),"label":str(a.get("label",""))} for a in refs]}
            if refs:text=_ai_index_svc.with_context(text,refs)
        stream_id=_ai_chat_svc.start_stream(provider_kind,history,text,meta)
        return {"stream_id":stream_id,"session_id":session_id}
    def chat_send_stream_poll(self,session_id,provider_kind,stream_id):
        r=_ai_chat_svc.poll_stream(stream_id)
        if r.get("done") and r.get("history") is not None:
            _ai_sessions_svc.save_session_messages(session_id,r["history"],provider_kind)
        return r
    def chat_abort_stream(self,stream_id):
        return _ai_chat_svc.abort_stream(stream_id)
    def pricing_table(self):
        return _ai_svc.PRICING_PER_1K_TOKENS
    def complete(self,query,kinds=None,limit=8):
        return _ai_index_svc.suggest(query or "",kinds or None,limit)
    def context_preview(self,refs):
        return _ai_index_svc.context_for(refs or [])
    def live_target(self):
        return _ai_index_svc.live_target()
    def resolve_placeholders(self,text):
        return _ai_index_svc.resolve_placeholders(text or "")
    def semantic_status(self):
        return _semantic_svc.status()
    def semantic_rebuild(self):
        return _semantic_svc.rebuild_index()
    def sessions(self):
        return _ai_sessions_svc.list_sessions()
    def new_session(self,provider_kind=""):
        return _ai_sessions_svc.create_session(provider_kind)
    def get_session(self,session_id):
        return _ai_sessions_svc.load_session(session_id)
    def clear_session(self,session_id):
        return _ai_sessions_svc.clear_session(session_id)
    def delete_session(self,session_id):
        return _ai_sessions_svc.delete_session(session_id)
    def rename_session(self,session_id,title):
        return _ai_sessions_svc.rename_session(session_id,title)
    def permission_rows(self):
        return _ai_svc.permission_rows()
    def set_permission(self,key,enabled):
        return _ai_svc.set_permission(key,enabled)
    def set_permissions_bulk(self,keys,enabled):
        return _ai_svc.set_permissions_bulk(keys,enabled)
    def terminal_approval_mode(self):
        return _ai_svc.terminal_approval_mode()
    def set_terminal_approval_mode(self,mode):
        return _ai_svc.set_terminal_approval_mode(mode)
    def select_all_permissions(self):
        return _ai_svc.select_all_permissions()
    def deselect_all_permissions(self):
        return _ai_svc.deselect_all_permissions()
    def assign_all_delete_permissions(self):
        return _ai_svc.assign_all_delete_permissions()
    def clear_all_delete_permissions(self):
        return _ai_svc.clear_all_delete_permissions()
    def roles_state(self):
        return _ai_svc.roles_state()
    def set_permission_levels(self,levels):
        _ai_svc.set_permission_levels(levels)
        return _ai_svc.roles_state()
    def apply_preset(self,preset_id):
        _ai_svc.apply_preset(preset_id)
        return _ai_svc.roles_state()
    def pending_approvals(self):
        return _ai_svc.pending_approvals()
    def resolve_approval(self,approval_id,decision):
        return _ai_svc.resolve_approval(approval_id,decision)
    def revoke_session_grant(self,key=None):
        _ai_svc.revoke_session_grant(key)
        return _ai_svc.roles_state()
    def activity(self,limit=50):
        return _ai_svc.activity(limit)
# While the app is locked (auto-lock or before the PIN at startup) every bridge call that can read or change user data is refused.
# None = whole module stays open; a set = only those methods stay open (boot-time settings reads and terminal output polling).
_LOCK_OPEN={"window":None,"theme":None,"security":{"status","is_locked","needs_unlock","unlock","lock"},"focusMode":None,"terminal":{"shells","get_settings","alive","exit_code","resize","batch_output_info"},"ai":{"get_settings","pricing_table"},"update":{"status","launch_ready"}}
_LOCK_OPEN_TOP={"ping","bind","settings","save_settings"}
def _locked_guard(fn):
    def call(*a,**k):
        if _common_db.is_locked():raise ValueError("LOYA NG is locked. Unlock it to continue.")
        return fn(*a,**k)
    call.__name__=getattr(fn,"__name__","call");call.__doc__=getattr(fn,"__doc__",None)
    return call
def _guard_methods(obj,open_names):
    for name in dir(type(obj)):
        if name.startswith("_") or name=="bind" or name in open_names:continue
        fn=getattr(obj,name,None)
        if callable(fn) and not isinstance(fn,type) and hasattr(fn,"__self__"):setattr(obj,name,_locked_guard(fn))
def _hide_from_js(obj,name="bind"):
    # bind() takes the pywebview window object and is called from Python only. pywebview skips attributes marked
    # _serializable=False, so the page cannot call e.g. reports.bind("x") and swap the module's window for a string.
    fn=getattr(obj,name,None)
    if not callable(fn):return
    def py_only(*a,**k):return fn(*a,**k)
    py_only.__name__=name;py_only._serializable=False
    setattr(obj,name,py_only)
def _guard_while_locked(api):
    for mod_name,mod in list(vars(api).items()):
        if mod_name.startswith("_") or not hasattr(mod,"__module__") or callable(mod):continue
        _hide_from_js(mod)
        open_names=_LOCK_OPEN.get(mod_name,set())
        if open_names is None:continue
        _guard_methods(mod,open_names)
    _guard_methods(api,_LOCK_OPEN_TOP)
    _hide_from_js(api)
from Cores.Bridge.reports_api import ReportsAPI
from Cores.Bridge.evidence_api import EvidenceAPI
from Cores.Bridge.reports_io_api import ReportsIOAPI
from Cores.Bridge.report_ai_api import ReportAIAPI
from Cores.Bridge.ext_agents_api import ExternalAgentsAPI
from Cores.Bridge.cve_api import CveAPI
from Cores.Bridge.wsl_api import WslAPI
from Cores.Bridge.flows_api import FlowsAPI
from Cores.Bridge.chain_history_api import ChainHistoryAPI
class Api:
    def __init__(self):
        self.window=WindowAPI()
        self.theme=ThemeAPI()
        self.dashboard=DashboardAPI()
        self.notes=NotesAPI()
        self.commands=CommandsAPI()
        self.playbooks=PlaybooksAPI()
        self.targets=TargetsAPI()
        self.search=SearchAPI()
        self.security=SecurityAPI()
        self.backup=BackupAPI()
        self.recycleBin=RecycleBinAPI()
        self.notifications=NotificationsAPI()
        self.onboarding=OnboardingAPI()
        self.focusMode=FocusModeAPI()
        self.tags=TagsAPI()
        self.importExport=ImportExportAPI()
        self.templates=TemplatesAPI()
        self.update=UpdateAPI()
        self.terminal=TerminalAPI()
        self.ai=AIAPI()
        self.reports=ReportsAPI()
        self.evidence=EvidenceAPI()
        self.reportsIO=ReportsIOAPI()
        self.reportAI=ReportAIAPI()
        self.extAgents=ExternalAgentsAPI()
        self.cve=CveAPI()
        self.wsl=WslAPI()
        self.flows=FlowsAPI()
        self.chainHistory=ChainHistoryAPI()
        _guard_while_locked(self)
        # Plain copies made by "Open attachment" in a run that was killed (no atexit) are removed at the next start.
        threading.Thread(target=_notes_svc.sweep_stale_attachment_copies,daemon=True,name="loya-att-sweep").start()
    def bind(self,window,maximized=False,pre_geo=None):
        self.window.bind(window,maximized,pre_geo)
        self.dashboard.bind(window)
        self.notes.bind(window)
        self.backup.bind(window)
        self.importExport.bind(window)
        self.templates.bind(window)
        self.terminal.bind(window)
        self.reports.bind(window)
        self.evidence.bind(window)
        self.reportsIO.bind(window)
        self.reportAI.bind(window)
        self.flows.bind(window)
        self.chainHistory.bind(window)
    def ping(self):
        return {"pong":True,"ts":time.time()}
def _default_size(screen_w,screen_h):
    w=max(760,int(screen_w*0.8));h=max(520,int(screen_h*0.8))
    return min(w,screen_w),min(h,screen_h)
def _rect_from_obj(obj):
    if obj is None:return None
    vals=[]
    for names in (("X","x"),("Y","y"),("Width","width"),("Height","height")):
        found=None
        for name in names:
            if hasattr(obj,name):
                try:found=int(getattr(obj,name));break
                except Exception:pass
        if found is None:return None
        vals.append(found)
    return tuple(vals)
def _screen_for_window(window):
    screens=webview.screens
    if not screens:return None
    try:
        cx=int(window.x)+max(1,int(window.width))//2
        cy=int(window.y)+max(1,int(window.height))//2
    except Exception:
        return screens[0]
    for scr in screens:
        if cx>=scr.x and cx<scr.x+scr.width and cy>=scr.y and cy<scr.y+scr.height:return scr
    return screens[0]
def _gdk_work_area(cx,cy):
    import gi
    gi.require_version("Gdk","3.0")
    from gi.repository import Gdk
    display=Gdk.Display.get_default()
    monitor=display.get_monitor_at_point(cx,cy) if hasattr(display,"get_monitor_at_point") else None
    if monitor is None and hasattr(display,"get_monitor"):monitor=display.get_monitor(0)
    rect=monitor.get_workarea() if monitor and hasattr(monitor,"get_workarea") else None
    return _rect_from_obj(rect)
def _linux_work_area(scr):
    if not sys.platform.startswith("linux") or not scr:return None
    cx=scr.x+(scr.width//2);cy=scr.y+(scr.height//2)
    try:
        vals=_run_on_gtk_main(lambda:_gdk_work_area(cx,cy))
        if vals:return vals
    except Exception:pass
    try:
        out=subprocess.check_output(["xprop","-root","_NET_WORKAREA"],stderr=subprocess.DEVNULL,text=True,timeout=1)
        nums=[int(v) for v in out.split("=")[-1].replace(","," ").split() if v.lstrip("-").isdigit()]
        rects=[tuple(nums[i:i+4]) for i in range(0,len(nums)-3,4)]
        for x,y,w,h in rects:
            if cx>=x and cx<x+w and cy>=y and cy<y+h:return x,y,w,h
        if rects:return rects[0]
    except Exception:pass
    return None
def _work_area_for_window(window):
    scr=_screen_for_window(window)
    if not scr:return 0,0,900,650
    vals=_linux_work_area(scr) or _rect_from_obj(getattr(scr,"frame",None))
    if vals:
        x,y,w,h=vals
        return x,y,max(MIN_W,w),max(MIN_H,h)
    reserve=48 if sys.platform.startswith("linux") else 0
    return int(scr.x),int(scr.y),max(MIN_W,int(scr.width)),max(MIN_H,int(scr.height)-reserve)
def _on_screen(x,y,w,h,screens):
    if x is None or y is None:return True
    if not screens:return True
    margin=40
    for scr in screens:
        if x+w>scr.x+margin and x<scr.x+scr.width-margin and y+h>scr.y+margin and y<scr.y+scr.height-margin:
            return True
    return False
def _window_background():
    try:return _tokens.GLASS.get(_tokens.current_theme(),_tokens.GLASS["dark"])["bg"]
    except Exception:return "#05060a"
def _window_color_kwargs():
    return {"background_color":_window_background()} if _IS_LINUX else {}
# Rounded window corners. Linux: a transparent GTK window (RGBA visual) lets the page clip its own background to a rounded rect
# (base.css html.window-rounded); only when a compositor is running, otherwise the corners would turn black, so they stay square.
# LOYA_SQUARE_WINDOW=1 turns it off. Windows 11: DWM rounds the frameless window itself (see _win_round_corners); no transparency.
_ROUNDED_WINDOWS={}
_CAN_ROUND=[]
def _linux_can_round():
    """Probed once, when the main window is created on the startup thread (the mini window is created later from a bridge thread)."""
    if _CAN_ROUND:return _CAN_ROUND[0]
    ok=False
    if _IS_LINUX and not os.environ.get("LOYA_SQUARE_WINDOW"):
        try:
            from gi.repository import Gdk
            scr=Gdk.Screen.get_default()
            ok=bool(scr is not None and scr.is_composited() and scr.get_rgba_visual() is not None)
        except Exception:ok=False
    _CAN_ROUND.append(ok)
    return ok
def _round_kwargs(name):
    rounded=_linux_can_round()
    _ROUNDED_WINDOWS[name]=rounded
    return {"transparent":True} if rounded else {}
def _win_round_corners(window):
    """Windows 11 only: ask DWM for rounded corners on the frameless window. Fails harmlessly on Windows 10 (no such attribute)."""
    if not sys.platform.startswith("win"):return False
    try:
        import ctypes
        from webview.platforms.winforms import BrowserView
        inst=BrowserView.instances.get(window.uid)
        if inst is None:return False
        hwnd=inst.Handle.ToInt32()
        DWMWA_WINDOW_CORNER_PREFERENCE=33;DWMWCP_ROUND=2
        pref=ctypes.c_int(DWMWCP_ROUND)
        return ctypes.windll.dwmapi.DwmSetWindowAttribute(ctypes.c_void_p(hwnd),ctypes.c_uint(DWMWA_WINDOW_CORNER_PREFERENCE),ctypes.byref(pref),ctypes.sizeof(pref))==0
    except Exception:return False
def _mini_seed_geometry(x,y,w,h,screens):
    if not _IS_LINUX:return None
    if x is not None and y is not None:return (int(x),int(y),int(w),int(h))
    if not screens:return None
    scr=screens[0]
    return (int(scr.x)+(int(scr.width)-int(w))//2,int(scr.y)+(int(scr.height)-int(h))//2,int(w),int(h))
# ---- navigation guard (H-05). pywebview injects window.pywebview.api into whatever page the window shows, so the windows must
# never leave the app's own UI files: a note link, window.location, a form or a dropped URL that navigated the top frame would
# hand the Python bridge to that page. The UI blocks these in JS (UI/js/components/nav-guard.js); this is the native backstop.
def _ui_root_dir():return _root("UI")
def _nav_allowed(uri,ui_root=None):
    """True for the app's own pages (file: URLs inside UI/) and for about:blank / about:srcdoc (sandboxed report previews)."""
    from urllib.parse import urlsplit,unquote
    u=str(uri or "").strip()
    if u in ("about:blank","about:srcdoc"):return True
    try:parts=urlsplit(u)
    except Exception:return False
    if parts.scheme.lower()!="file" or parts.netloc not in ("","localhost"):return False
    path=unquote(parts.path)
    if re.match(r"^/[A-Za-z]:[/\\]",path):path=path[1:]
    if "\x00" in path:return False
    root=os.path.normcase(os.path.realpath(ui_root or _ui_root_dir()))
    try:target=os.path.normcase(os.path.realpath(path))
    except Exception:return False
    try:return os.path.commonpath([target,root])==root
    except ValueError:return False
def _install_nav_guard(window):
    """Cancel every top-level navigation away from UI/. GTK: our decide-policy handler runs after pywebview's and ignores the
    decision. WebView2: NavigationStarting with Cancel. Failures are logged; the JS guard still applies."""
    def blocked(uri):_diag_log.warning(f"[nav-guard] blocked navigation to {str(uri)[:200]}")
    try:
        if _IS_LINUX:
            view=_gtk_view(window)
            if view is None or getattr(view,"_loya_nav_guard",False):return False
            def on_policy(webview,decision,decision_type):
                from webview.platforms import gtk as _pw_gtk
                if isinstance(decision,_pw_gtk.webkit.NavigationPolicyDecision):
                    uri=decision.get_navigation_action().get_request().get_uri()
                    if not _nav_allowed(uri):
                        blocked(uri);decision.ignore();return True
                return False
            def connect():
                view.webview.connect("decide-policy",on_policy);view._loya_nav_guard=True
                return False
            _run_on_gtk_main(connect)
            return True
        if sys.platform.startswith("win"):
            from webview.platforms.winforms import BrowserView
            inst=BrowserView.instances.get(window.uid)
            wv=getattr(getattr(inst,"browser",None),"webview",None)
            if wv is None or getattr(inst,"_loya_nav_guard",False):return False
            def on_nav(sender,args):
                try:
                    uri=str(args.Uri)
                    if not _nav_allowed(uri):blocked(uri);args.Cancel=True
                except Exception:pass
            wv.NavigationStarting+=on_nav
            inst._loya_nav_guard=True
            return True
    except Exception as e:
        _diag_log.warning(f"[nav-guard] native guard not installed: {e}")
    return False
class _TooltipClickGate:
    """After a click, no tooltip until the pointer really moves (what Chromium/WebView2 does). WebKitGTK only refreshes its
    tooltip text on pointer motion, so GTK re-showed the clicked button's title over the popover the click had just opened."""
    SLOP=3
    def __init__(self):self.pressed_at=None;self.last=None
    def press(self,x,y):self.pressed_at=(x,y)
    # Scrolling or typing moves or re-renders what is under a still pointer (a list filtered as you type, a scrolled table):
    # the tooltip GTK holds belongs to whatever was there before, so it waits for motion too.
    def hold(self):self.pressed_at=self.last or (-10**6,-10**6)
    def motion(self,x,y):
        self.last=(x,y)
        if self.pressed_at and (abs(x-self.pressed_at[0])>self.SLOP or abs(y-self.pressed_at[1])>self.SLOP):self.pressed_at=None
    def allow(self):return self.pressed_at is None
def _install_tooltip_click_hide(window):
    if not _IS_LINUX:return False
    view=_gtk_view(window)
    if view is None or getattr(view,"_loya_tip_gate",False):return False
    gate=_TooltipClickGate()
    def on_press(w,ev):gate.press(ev.x,ev.y);return False
    def on_motion(w,ev):gate.motion(ev.x,ev.y);return False
    # GTK already hides a shown tooltip on scroll and key press; the gate keeps it from coming back with the old text.
    def on_hold(w,ev):gate.hold();return False
    def on_query(w,x,y,keyboard,tip):
        if keyboard or gate.allow():return False
        w.stop_emission_by_name("query-tooltip");return False
    def connect():
        try:
            wv=view.webview
            wv.connect("button-press-event",on_press);wv.connect("motion-notify-event",on_motion);wv.connect("query-tooltip",on_query)
            wv.connect("scroll-event",on_hold);wv.connect("key-press-event",on_hold)
            view._loya_tip_gate=True
        except Exception as e:_diag_log.warning(f"[tooltip] click gate not installed: {e}")
        return False
    _run_on_gtk_main(connect)
    return True
def _harden_webview_settings():
    # A target=_blank link or window.open() would otherwise go to webbrowser.open() with any scheme (on Windows os.startfile:
    # ms-msdt:, file:, search-ms: ...). With this off pywebview loads it in-window instead, where the guard above cancels it.
    try:webview.settings["OPEN_EXTERNAL_LINKS_IN_BROWSER"]=False
    except Exception:pass
def create_main_window():
    _tokens.write()
    api=Api()
    geo=load_window_geometry()
    screens=webview.screens
    scr=screens[0] if screens else None
    sw=int(scr.width) if scr else 1280
    sh=int(scr.height) if scr else 800
    gw=int(geo.get("w",0) or 0);gh=int(geo.get("h",0) or 0)
    if gw>=MIN_W and gh>=MIN_H:
        w,h=min(gw,sw),min(gh,sh)
        gx=geo.get("x");gy=geo.get("y")
        if not _on_screen(gx,gy,w,h,screens):gx=None;gy=None
    else:
        w,h=_default_size(sw,sh);gx=None;gy=None
    maximized=bool(geo.get("maximized"))
    html_path=_root("UI","windows","main.html").replace("\\","/")
    window=webview.create_window("LOYA NG",f"file:///{html_path}",js_api=api,width=w,height=h,x=gx,y=gy,min_size=(MIN_W,MIN_H),frameless=True,easy_drag=False,resizable=True,maximized=False,**_window_color_kwargs(),**_round_kwargs("main"))
    api.bind(window,maximized,(gx or 0,gy or 0,w,h))
    if sys.platform.startswith("win"):window.events.shown+=lambda:_win_round_corners(window)
    _harden_webview_settings()
    window.events.shown+=lambda:_install_nav_guard(window)
    window.events.shown+=lambda:_install_tooltip_click_hide(window)
    _windows["main"]=window
    return window,api
def create_mini_window():
    api=MiniApi()
    cfg=_quick_svc._get_mini_settings()
    w=max(MINI_MIN_W,int(cfg.get("w",520) or 520));h=max(MINI_MIN_H,int(cfg.get("h",420) or 420))
    x=cfg.get("x");y=cfg.get("y")
    if not _on_screen(x,y,w,h,webview.screens):x=None;y=None
    html_path=_root("UI","windows","mini.html").replace("\\","/")
    window=webview.create_window("LOYA NG Mini",f"file:///{html_path}",js_api=api,width=w,height=h,x=x,y=y,min_size=(MINI_MIN_W,MINI_COLLAPSED_H),frameless=True,easy_drag=False,resizable=True,on_top=bool(cfg.get("always_on_top")),**_window_color_kwargs(),**_round_kwargs("mini"))
    if sys.platform.startswith("win"):window.events.shown+=lambda:_win_round_corners(window)
    window.events.shown+=lambda:_install_nav_guard(window)
    window.events.shown+=lambda:_install_tooltip_click_hide(window)
    api.window.bind(window,_mini_seed_geometry(x,y,w,h,webview.screens),(w,h))
    _windows["mini"]=window
    return window,api
if __name__=="__main__":
    create_main_window()
    webview.start(gui="edgechromium")
