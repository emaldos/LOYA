import sys,shutil,subprocess,base64
_NOTIFY_BUS_NAME="org.freedesktop.Notifications"
def _is_windows():return sys.platform.startswith("win")
def _ps_escape(s):
    return (s or "").replace("`","``").replace('"','""').replace("$","`$")
def _ps_literal(s):
    # Text reaches the script only as base64 inside a single-quoted literal. Escaping a "..." string is not enough: PowerShell also
    # ends it at the typographic quotes U+201C/U+201D/U+201E, so a report name like  x”;calc;“  would run code.
    b64=base64.b64encode(str(s or "").encode("utf-8")).decode("ascii")
    return f"([Text.Encoding]::UTF8.GetString([Convert]::FromBase64String('{b64}')))"
def _dbus_call(method,*args):
    return subprocess.run(["gdbus","call","--session","--dest","org.freedesktop.DBus","--object-path","/org/freedesktop/DBus","--method",method,*args],capture_output=True,text=True,timeout=3)
def notification_daemon_available():
    if not shutil.which("gdbus"):return True
    try:
        owned=_dbus_call("org.freedesktop.DBus.NameHasOwner",_NOTIFY_BUS_NAME)
        if owned.returncode==0 and "true" in (owned.stdout or "").lower():return True
        activatable=_dbus_call("org.freedesktop.DBus.ListActivatableNames")
        return activatable.returncode==0 and _NOTIFY_BUS_NAME in (activatable.stdout or "")
    except Exception:
        return False
def available():
    if _is_windows():return True
    try:
        if subprocess.run(["which","notify-send"],capture_output=True,timeout=2).returncode!=0:return False
    except Exception:
        return False
    return notification_daemon_available()
def send(title,message,app_name="LOYA NG"):
    try:
        if _is_windows():return _send_windows(title,message,app_name)
        return _send_linux(title,message,app_name)
    except Exception:
        return False
def _send_windows(title,message,app_name):
    ps=(
        '[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;'
        '[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null;'
        '$t = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);'
        '$texts = $t.GetElementsByTagName("text");'
        f'$texts.Item(0).AppendChild($t.CreateTextNode({_ps_literal(title)})) | Out-Null;'
        f'$texts.Item(1).AppendChild($t.CreateTextNode({_ps_literal(message)})) | Out-Null;'
        '$toast = [Windows.UI.Notifications.ToastNotification]::new($t);'
        f'[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier({_ps_literal(app_name)}).Show($toast);'
    )
    creationflags=getattr(subprocess,"CREATE_NO_WINDOW",0)
    r=subprocess.run(["powershell","-NoProfile","-NonInteractive","-Command",ps],capture_output=True,timeout=6,creationflags=creationflags)
    return r.returncode==0
def _send_linux(title,message,app_name):
    r=subprocess.run(["notify-send","--app-name",app_name,"--",title,message],capture_output=True,timeout=6)
    return r.returncode==0
