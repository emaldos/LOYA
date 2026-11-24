import os,sys,logging,time,subprocess,json,threading
from datetime import datetime,timezone
from logging.handlers import RotatingFileHandler
import webview
from Cores.Update import health_check as _health_check
from Cores.Update import APP_NAME as _UPDATE_APP_NAME
from Cores.Update import DEFAULT_APP_VERSION as _DEFAULT_APP_VERSION
from Cores.Update import ensure_runtime_files as _ensure_update_runtime
from Cores.Update import get_app_version as _get_app_version
from Cores.Update import get_windows_app_id as _get_windows_app_id
from Cores.Update import sync_installed_version as _sync_installed_version
from Cores.Services.settings_service import auto_backup_if_needed as _auto_backup_if_needed
from Cores.Services.settings_service import get_notification_settings as _get_notification_settings
from Cores import os_toast as _os_toast
from Cores.Bridge import api as _bridge_api
from Cores.Update import update_service as _update_svc
from Cores.Services import security_service as _security
from Cores import common_db as _common_db
from Cores import settings_lock as _settings_lock
APP_NAME=_UPDATE_APP_NAME
def _abs(*p):return os.path.join(os.path.dirname(os.path.abspath(__file__)),*p)
def _app_version():
    try:return _get_app_version()
    except Exception:return _DEFAULT_APP_VERSION
DEFAULT_LOG_RETENTION_DAYS=30
def _read_settings_json():
    try:
        with open(_abs("Data","settings.json"),"r",encoding="utf-8") as f:
            d=json.load(f)
        return d if isinstance(d,dict) else {}
    except Exception:
        return {}
def _log_retention_days():
    try:
        v=int(_read_settings_json().get("log_retention_days",DEFAULT_LOG_RETENTION_DAYS))
        return v if v>0 else DEFAULT_LOG_RETENTION_DAYS
    except Exception:
        return DEFAULT_LOG_RETENTION_DAYS
def _purge_old_logs(days=None):
    if days is None:days=_log_retention_days()
    try:
        d=_abs("Logs")
        if not os.path.isdir(d):return 0
        cut=time.time()-(days*86400);n=0
        for name in os.listdir(d):
            p=os.path.join(d,name)
            if not os.path.isfile(p):continue
            try:
                if os.path.getmtime(p)<cut:os.remove(p);n+=1
            except Exception:pass
        return n
    except Exception:return 0
def _log_setup():
    d=_abs("Logs");os.makedirs(d,exist_ok=True)
    lg=logging.getLogger("Note");lg.setLevel(logging.INFO)
    if lg.handlers:return lg
    h=RotatingFileHandler(os.path.join(d,"Note_log.log"),maxBytes=1024*1024,backupCount=5,encoding="utf-8")
    h.setFormatter(logging.Formatter("%(asctime)s %(message)s","%Y-%m-%d %H:%M:%S"))
    lg.addHandler(h);return lg
_LOG=None
def _log(tag,msg):
    global _LOG
    if _LOG is None:_LOG=_log_setup()
    try:_LOG.info(f"{tag} {msg}")
    except Exception:pass
def _console_python():
    py=os.path.abspath(sys.executable)
    if os.name=="nt" and py.lower().endswith("pythonw.exe"):
        alt=py[:-5]+".exe"
        if os.path.isfile(alt):return alt
    return py
def _open_recovery_mode(reason=""):
    script=_abs("RunNote.py")
    if not os.path.isfile(script):return False
    cmd=[_console_python(),script,"--recovery"]
    if reason:cmd+=["--reason",str(reason)]
    try:
        if os.name=="nt":subprocess.Popen(cmd,cwd=_abs(),stdin=subprocess.DEVNULL,creationflags=0x00000010)
        else:subprocess.Popen(cmd,cwd=_abs(),stdin=subprocess.DEVNULL,start_new_session=True)
        return True
    except Exception as e:
        _log("[!]",f"Recovery launcher failed ({e})")
        return False
def _remove_pid_file():
    p=_abs("Data","loya.pid")
    try:
        with open(p,"r",encoding="utf-8") as f:owner=int(f.read().strip())
    except (OSError,ValueError):return
    try:launcher_pids=(os.getpid(),os.getppid())
    except OSError:launcher_pids=(os.getpid(),)
    if owner not in launcher_pids:return
    try:os.remove(p)
    except OSError:pass
def _set_windows_app_id():
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes
        app_id=_get_windows_app_id(_app_version())
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(app_id)
        _log("[+]",f"AppUserModelID set: {app_id}")
    except Exception as e:
        _log("[-]",f"AppUserModelID failed ({e})")
_DAMAGE_FEATURES=("PropagateDamagingInformation","UnifyDamagedRegions","UseDamagingInformationForCompositing")
def _disable_webkit_damage_tracking():
    if sys.platform.startswith("win"):return "skipped (windows)"
    try:
        from gi.repository import GLib,WebKit2
        from webview.platforms.gtk import BrowserView
    except Exception as exc:
        return f"unavailable ({exc})"
    state={"tries":0}
    def apply():
        state["tries"]+=1
        try:
            views=list(BrowserView.instances.values())
            if not views:return state["tries"]<40
            features=WebKit2.Settings.get_all_features()
            wanted=[features.get(i) for i in range(features.get_length()) if (features.get(i).get_identifier() or "") in _DAMAGE_FEATURES]
            for view in views:
                settings=view.webview.get_settings()
                for feature in wanted:settings.set_feature_enabled(feature,False)
            _log("[+]",f"WebKit damage tracking disabled ({len(wanted)} features on {len(views)} view(s))")
        except Exception as exc:
            _log("[-]",f"WebKit damage tracking not adjusted ({exc})")
        return False
    GLib.timeout_add(150,apply)
    return "scheduled on the GTK main loop"
def _enable_gtk_overwrite_confirmation():
    if sys.platform.startswith("win"):return "skipped (windows)"
    try:
        from gi.repository import Gtk
        from webview.platforms.gtk import BrowserView
    except Exception as exc:
        return f"unavailable ({exc})"
    original=getattr(BrowserView,"_add_file_filters",None)
    if original is None:return "unavailable (pywebview no longer has BrowserView._add_file_filters)"
    if getattr(original,"_loya_overwrite_confirm",False):return "already installed"
    def _add_file_filters(self,dialog,file_types):
        original(self,dialog,file_types)
        try:
            if dialog.get_action()==Gtk.FileChooserAction.SAVE:dialog.set_do_overwrite_confirmation(True)
        except Exception as exc:
            _log("[-]",f"Save dialog overwrite confirmation not set ({exc})")
    _add_file_filters._loya_overwrite_confirm=True
    BrowserView._add_file_filters=_add_file_filters
    return "installed"
SCHEDULER_TICK_SECONDS=600
_SCHED_STOP=threading.Event()
def _parse_iso(ts):
    try:
        dt=datetime.fromisoformat(str(ts).strip().replace("Z","+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except Exception:return None
def _update_check_due(cfg,last_checked,now=None):
    if not (cfg or {}).get("auto_enabled"):return False
    last=_parse_iso(last_checked)
    if last is None:return True
    try:hrs=max(1,int(cfg.get("check_interval_hours",24)))
    except Exception:hrs=24
    now=now or datetime.now(timezone.utc)
    return (now-last).total_seconds()>=hrs*3600 or last>now
def _notify_update_once(ver):
    # The in-app notice handles the visible window; the OS toast is for a hidden/minimised window and fires once per version.
    try:
        cfg=_update_svc.get_update_settings()
        if not ver or cfg.get("notified_version")==ver or cfg.get("skipped_version")==ver:return False
        _update_svc.save_update_settings({"notified_version":ver})
        if _get_notification_settings().get("os_enabled"):
            _os_toast.send("LOYA NG",f"LOYA NG {ver} is available. Open the app to see what's new and update.")
        return True
    except Exception:return False
def _maybe_check_updates(now=None):
    # check_for_updates stamps last_checked even when offline, so a failing network is retried once per interval, silently.
    try:
        cfg=_update_svc.get_update_settings()
        state=_update_svc.get_update_state()
        if state.get("update_in_progress"):return None
        if not _update_check_due(cfg,state.get("last_checked") or cfg.get("last_checked"),now):return None
        out=_update_svc.check_for_updates(timeout=10)
        try:_update_svc.sync_update_settings_from_state(out.get("state"))
        except Exception:pass
        if out.get("ok") and out.get("update_available"):
            ver=(out.get("state") or {}).get("last_available_version","")
            _log("[+]",f"Update available: {ver}")
            _notify_update_once(ver)
        return out
    except Exception:return None
_STAGE_RETRY_SECONDS=6*3600
_STAGE_FAILED={}
def _maybe_stage_update(now=None):
    # "Download in the background and install on next restart": fetch + verify the package; RunNote.py installs it at the next start.
    latest=""
    try:
        cfg=_update_svc.get_update_settings()
        if not cfg.get("auto_enabled") or cfg.get("on_available")!="background":return None
        st=_update_svc.get_update_state()
        cur=st.get("current_version","");latest=st.get("last_available_version","")
        if st.get("update_in_progress") or not latest or not st.get("asset_name"):return None
        if cfg.get("skipped_version")==latest or _update_svc.staged_update_info(st):return None
        from Cores.Update import update_helpers as _uh
        if _uh.compare_semver(latest,cur)<=0:return None
        t=time.time() if now is None else now
        last=_STAGE_FAILED.get(latest)
        if last and t-last<_STAGE_RETRY_SECONDS:return None
        out=_update_svc.stage_update(timeout=120)
        _log("[+]",f"Update {latest} downloaded in the background; it installs on the next start")
        return out
    except Exception as e:
        if latest:_STAGE_FAILED[latest]=time.time() if now is None else now
        _log("[-]",f"Background update download failed ({e})")
        return None
def _scheduled_auto_backup():
    if _common_db.db_locked():return None
    try:
        ok,msg=_auto_backup_if_needed()
        if ok:
            _log("[+]",f"Auto backup: {msg}")
            if _get_notification_settings().get("os_enabled"):_os_toast.send("LOYA NG","Auto backup completed: "+msg)
        return ok,msg
    except Exception as e:
        _log("[-]",f"Auto backup failed ({e})")
        return None
def _scheduled_audit_prune():
    try:
        n=_security.prune_audit_log()
        if n:_log("[*]",f"Security audit log: pruned {n} expired entries")
        return n
    except Exception:return 0
def _scheduled_report_reminders():
    # OS notifications only: the in-app toast for the same reminder is fetched by the UI (reports.reminders_due), and each
    # channel records its own delivery, so a reminder shows once in each place. Skipped quietly while locked.
    try:
        from Cores.Services import report_schedule as _report_schedule
        return _report_schedule.notify_os(_os_toast.send,_get_notification_settings().get("os_enabled"))
    except Exception:return 0
def _scheduler_tick():
    _scheduled_audit_prune()
    _scheduled_auto_backup()
    _scheduled_report_reminders()
    _maybe_check_updates()
    _maybe_stage_update()
def _scheduler_loop(first_delay=5):
    if _SCHED_STOP.wait(first_delay):return
    while True:
        try:_scheduler_tick()
        except Exception:pass
        if _SCHED_STOP.wait(SCHEDULER_TICK_SECONDS):return
def _start_background_scheduler():
    t=threading.Thread(target=_scheduler_loop,name="loya-scheduler",daemon=True)
    t.start()
    return t
def _after_window_shown():
    try:
        _log("[+]","GTK save overwrite confirmation: "+_enable_gtk_overwrite_confirmation())
    except Exception as e:
        _log("[-]",f"GTK save overwrite confirmation not installed ({e})")
    try:
        _log("[+]","WebKit damage tracking: "+_disable_webkit_damage_tracking())
    except Exception as e:
        _log("[-]",f"WebKit damage tracking not adjusted ({e})")
    try:
        ok,msg=_auto_backup_if_needed()
        _log("[+]" if ok else "[*]",f"Auto backup: {msg}")
        if ok and _get_notification_settings().get("os_enabled"):
            _os_toast.send("LOYA NG","Auto backup completed: "+msg)
    except Exception as e:
        _log("[-]",f"Auto backup failed ({e})")
    # A just-installed update is confirmed by the UI once it has loaded (update.launch_ready -> health check), not here:
    # a window whose page fails to load must not count as a healthy start, so the apply helper can roll it back.
    try:_scheduled_audit_prune()
    except Exception:pass
    try:_start_background_scheduler()
    except Exception as e:_log("[-]",f"Background scheduler not started ({e})")
def main():
    try:
        _ensure_update_runtime()
        _sync_installed_version()
    except Exception as e:
        _log("[!]",f"Update runtime init failed ({e})")
    app_ver=_app_version()
    _log("[*]",f"Start {APP_NAME} v{app_ver}")
    _set_windows_app_id()
    _purge_old_logs()
    startup_report=_health_check.run_health_check(after_security=False)
    if startup_report.fatal:
        text=startup_report.fatal_text()
        _log("[-]",text.replace("\n"," | "))
        try:_health_check.mark_launch_completed(False,text)
        except Exception as e:_log("[!]",f"Launch failure record failed ({e})")
        _open_recovery_mode(text)
        return 8
    if startup_report.has_notice():
        _log("[*]",startup_report.notice_text().replace("\n"," | "))
    try:
        if _security.sync_lock_state():_log("[*]","Locked until the PIN is entered")
    except Exception as e:_log("[!]",f"Lock state init failed ({e})")
    try:
        # A Claude Code / Codex CLI connected under Settings > AI > Agents reaches LOYA through the local MCP server.
        from Cores.Services import ext_connections_service as _ext_conn
        if _ext_conn.autostart():_log("[*]","Starting the MCP server for connected CLIs")
    except Exception as e:_log("[!]",f"CLI connections init failed ({e})")
    try:_health_check.mark_launch_started()
    except Exception as e:_log("[!]",f"Launch state start failed ({e})")
    try:
        window,api=_bridge_api.create_main_window()
        _log("[+]","Window created")
        icon_name="logox.ico" if sys.platform.startswith("win") else "logox_256.png"
        icon_path=_abs("Assets",icon_name)
        if not os.path.isfile(icon_path):icon_path=_abs("Assets","logox.png")
        webview.start(_after_window_shown,debug=False,icon=icon_path if os.path.isfile(icon_path) else None)
    except Exception as e:
        msg=f"Window startup failed ({e})"
        _log("[!]",msg)
        try:_health_check.mark_launch_completed(False,msg)
        except Exception as state_exc:_log("[!]",f"Launch state failure record failed ({state_exc})")
        _open_recovery_mode(msg)
        return 9
    _SCHED_STOP.set()
    _remove_pid_file()
    try:_health_check.mark_launch_completed(True)
    except Exception as e:_log("[!]",f"Launch state completion failed ({e})")
    _log("[*]","Exit")
    return 0
if __name__=="__main__":raise SystemExit(main())
