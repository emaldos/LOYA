import sys,unittest
from _isolate import ROOT
from Cores import os_toast
class _Result:
    def __init__(self,returncode=0,stdout=""):
        self.returncode=returncode
        self.stdout=stdout
class _Fake:
    def __init__(self,has_notify_send=True,has_gdbus=True,owned=False,activatable=False,explode=False):
        self.has_notify_send=has_notify_send
        self.has_gdbus=has_gdbus
        self.owned=owned
        self.activatable=activatable
        self.explode=explode
        self.sent=[]
    def which(self,name):
        return "/usr/bin/"+name if (name=="gdbus" and self.has_gdbus) else None
    def run(self,cmd,**kwargs):
        if self.explode:raise OSError("bus unreachable")
        if cmd[:2]==["which","notify-send"]:return _Result(0 if self.has_notify_send else 1)
        if cmd[0]=="gdbus":
            method=cmd[cmd.index("--method")+1]
            if method.endswith("NameHasOwner"):return _Result(0,"(true,)" if self.owned else "(false,)")
            if method.endswith("ListActivatableNames"):return _Result(0,"org.freedesktop.Notifications" if self.activatable else "org.freedesktop.DBus")
        if cmd[0]=="notify-send":
            self.sent.append(cmd)
            return _Result(0)
        return _Result(1)
class ToastAvailabilityTests(unittest.TestCase):
    def setUp(self):
        self._is_windows=os_toast._is_windows
        self._shutil=os_toast.shutil
        self._subprocess=os_toast.subprocess
        os_toast._is_windows=lambda:False
    def tearDown(self):
        os_toast._is_windows=self._is_windows
        os_toast.shutil=self._shutil
        os_toast.subprocess=self._subprocess
    def _install(self,fake):
        os_toast.shutil=fake
        os_toast.subprocess=fake
        return fake
    def test_windows_is_always_available(self):
        os_toast._is_windows=lambda:True
        self.assertTrue(os_toast.available())
    def test_missing_notify_send_is_unavailable(self):
        self._install(_Fake(has_notify_send=False,owned=True))
        self.assertFalse(os_toast.available())
    def test_notify_send_without_a_running_daemon_is_unavailable(self):
        self._install(_Fake(owned=False,activatable=False))
        self.assertFalse(os_toast.available(),"reporting True here makes every notification fail silently")
    def test_a_running_daemon_is_available(self):
        self._install(_Fake(owned=True))
        self.assertTrue(os_toast.available())
    def test_a_dbus_activatable_daemon_is_available(self):
        self._install(_Fake(owned=False,activatable=True))
        self.assertTrue(os_toast.available(),"xfce4-notifyd is activated on demand, so it owns the name only once started")
    def test_without_gdbus_the_daemon_check_does_not_block_notifications(self):
        self._install(_Fake(has_gdbus=False,owned=False,activatable=False))
        self.assertTrue(os_toast.available())
    def test_a_broken_bus_is_unavailable(self):
        self._install(_Fake(explode=True))
        self.assertFalse(os_toast.available())
class ToastSendTests(unittest.TestCase):
    def setUp(self):
        self._is_windows=os_toast._is_windows
        self._subprocess=os_toast.subprocess
        os_toast._is_windows=lambda:False
    def tearDown(self):
        os_toast._is_windows=self._is_windows
        os_toast.subprocess=self._subprocess
    def test_send_passes_the_app_name_and_text(self):
        fake=_Fake()
        os_toast.subprocess=fake
        self.assertTrue(os_toast.send("Title","Body","LOYA NG"))
        self.assertEqual(1,len(fake.sent))
        self.assertIn("Title",fake.sent[0])
        self.assertIn("Body",fake.sent[0])
        self.assertIn("LOYA NG",fake.sent[0])
    def test_send_never_raises_when_the_bus_is_down(self):
        os_toast.subprocess=_Fake(explode=True)
        self.assertFalse(os_toast.send("Title","Body"))
if __name__=="__main__":unittest.main()
