"""Launch LOYA NG unchanged, plus: WebKit console -> stdout, and a file RPC
that evaluates JS in the main window (write cmd.js, read result.json)."""
import os, sys, json, time, threading
ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "..", "..", ".."))
import tempfile
HERE = os.environ.get("LOYA_AUDIT_DIR") or os.path.join(tempfile.gettempdir(), "loya-audit")
os.makedirs(HERE, exist_ok=True)
sys.path.insert(0, ROOT)
os.chdir(ROOT)
# env comes from the caller
import webview

CMD = os.path.join(HERE, "cmd.js")
RES = os.path.join(HERE, "result.json")

def _console_on():
    from gi.repository import GLib
    from webview.platforms.gtk import BrowserView
    def apply():
        views = list(BrowserView.instances.values())
        if not views:
            return True
        for v in views:
            v.webview.get_settings().set_enable_write_console_messages_to_stdout(True)
        print("[harness] console->stdout on", len(views), "view(s)", flush=True)
        return False
    GLib.timeout_add(100, apply)

# set_enable_write_console_messages_to_stdout() writes nothing on WebKitGTK 2.52, so JS errors are collected in-page
# (window.onerror, unhandledrejection, console.error/warn wrappers into window.__loyaErrs) and drained to stdout
# as "[js-error] ..." lines. Re-installed on every drain, so it survives reloads (errors before the first drain are missed).
COLLECT = r"""(function(){if(!window.__loyaErrHook){window.__loyaErrHook=1;window.__loyaErrs=window.__loyaErrs||[];
const push=(k,a)=>{try{window.__loyaErrs.push(k+" "+Array.from(a).map(x=>x&&x.message!==undefined?(x.name+": "+x.message+(x.stack?" | "+x.stack.split("\n")[0]:"")):(typeof x==="object"?JSON.stringify(x):String(x))).join(" ").slice(0,2000))}catch(e){}};
window.addEventListener("error",e=>push("onerror",[e.message+" @"+(e.filename||"")+":"+(e.lineno||0)]));
window.addEventListener("unhandledrejection",e=>push("unhandledrejection",[e.reason]));
["error","warn"].forEach(m=>{const o=console[m];console[m]=function(){push("console."+m,arguments);return o.apply(console,arguments)}})}
const out=window.__loyaErrs.splice(0);return JSON.stringify(out)})()"""

def _drain():
    for w in list(webview.windows):
        try:
            got = json.loads(w.evaluate_js(COLLECT) or "[]")
        except Exception:
            continue
        for line in got:
            print("[js-error] [%s] %s" % (w.title, line), flush=True)

def _rpc():
    last = 0.0
    while True:
        time.sleep(0.2)
        if time.time() - last > 1.0:
            last = time.time()
            _drain()
        if not os.path.exists(CMD):
            continue
        try:
            src = open(CMD).read()
            os.remove(CMD)
            # First line "//win:<title>" picks the window by title (js.sh LOYA_WIN=...); default: the main window.
            win = webview.windows[0]
            if src.startswith("//win:"):
                want = src.split("\n", 1)[0][6:].strip()
                win = next((w for w in webview.windows if w.title == want), None)
                if win is None:
                    raise RuntimeError("no window titled %r" % want)
            try:
                out = {"ok": True, "value": win.evaluate_js(src)}
            except Exception as e:
                out = {"ok": False, "error": repr(e)}
            tmp = RES + ".tmp"
            with open(tmp, "w") as f:
                json.dump(out, f, indent=1, default=str)
            os.replace(tmp, RES)
        except Exception as e:
            print("[harness] rpc error", e, flush=True)
            try:
                with open(RES + ".tmp", "w") as f:
                    json.dump({"ok": False, "error": repr(e)}, f)
                os.replace(RES + ".tmp", RES)
            except Exception:
                pass

_orig_start = webview.start
def _start(func=None, *a, **kw):
    def wrapped():
        _console_on()
        threading.Thread(target=_rpc, daemon=True).start()
        if func:
            func()
    return _orig_start(wrapped, *a, **kw)
webview.start = _start

import LOYA_Note
if os.environ.get('LOYA_KEEP_DAMAGE')=='1':
    LOYA_Note._disable_webkit_damage_tracking=lambda:'kept on (harness)'
raise SystemExit(LOYA_Note.main())
