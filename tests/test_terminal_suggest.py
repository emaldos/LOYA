import unittest
from _isolate import IsolatedData
from Cores.Services import terminal_service as terminal
class ShortcutSettingsTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
    def tearDown(self):
        self.isolated.stop()
    def test_defaults(self):
        settings=terminal.get_settings()
        self.assertTrue(settings["suggest_enabled"])
        self.assertEqual(terminal.SHORTCUT_DEFAULTS,settings["shortcuts"])
    def test_suggest_toggle_round_trips(self):
        terminal.set_run_behaviour({"suggest_enabled":False})
        self.assertFalse(terminal.get_settings()["suggest_enabled"])
        terminal.set_run_behaviour({"run_destination":"new"})
        self.assertFalse(terminal.get_settings()["suggest_enabled"])
    def test_normalize(self):
        self.assertEqual("Ctrl+Shift+Space",terminal.normalize_shortcut("shift+ctrl+space"))
        self.assertEqual("Alt+P",terminal.normalize_shortcut("alt + p"))
        self.assertEqual("F2",terminal.normalize_shortcut("f2"))
        self.assertEqual("",terminal.normalize_shortcut(""))
        for bad in ("p","Shift+F","Super+Space","Ctrl+Alt","Ctrl+Foo","Ctrl+A+B"):self.assertIsNone(terminal.normalize_shortcut(bad),bad)
    def test_set_and_reset(self):
        settings=terminal.set_shortcuts({"command_search":"alt+p"})
        self.assertEqual("Alt+P",settings["shortcuts"]["command_search"])
        self.assertEqual("Ctrl+Space",settings["shortcuts"]["suggest"])
        settings=terminal.set_shortcuts({"command_search":None})
        self.assertEqual("Ctrl+Shift+P",settings["shortcuts"]["command_search"])
    def test_clear_disables(self):
        self.assertEqual("",terminal.set_shortcuts({"suggest":""})["shortcuts"]["suggest"])
    def test_reserved_and_invalid_rejected(self):
        for combo in ("Ctrl+C","ctrl+r","Ctrl+Shift+C","Ctrl+Shift+V","Ctrl+Alt+T","Ctrl+3","x"):
            with self.assertRaises(ValueError,msg=combo):terminal.set_shortcuts({"suggest":combo})
        self.assertEqual("Ctrl+Space",terminal.get_settings()["shortcuts"]["suggest"])
    def test_duplicates_rejected(self):
        with self.assertRaises(ValueError):terminal.set_shortcuts({"suggest":"Ctrl+Shift+P"})
    def test_unknown_actions_ignored(self):
        settings=terminal.set_shortcuts({"launch_missiles":"Alt+M"})
        self.assertNotIn("launch_missiles",settings["shortcuts"])
    def test_tampered_settings_fall_back(self):
        d=terminal._read_settings()
        d["extensions"]={"terminal_shortcuts":{"suggest":"Ctrl+C","command_search":"garbage+"}}
        terminal._write_settings(d)
        shortcuts=terminal.get_settings()["shortcuts"]
        self.assertEqual("Ctrl+Space",shortcuts["suggest"])
        self.assertEqual("Ctrl+Shift+P",shortcuts["command_search"])
class CommandIndexTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
    def tearDown(self):
        self.isolated.stop()
    def test_build_dedupes_and_maps_family(self):
        rows=[{"command":"nmap {IPv4}","title":"Scan","category":"Recon","command_type":"Linux Shell"},{"command":"NMAP {IPv4}","title":"dup"},{"command":"  ","title":"empty"},{"command":"Get-Process","command_type":"PowerShell"},{"command":"dir","command_type":"CMD"},{"command":"select 1","command_type":"SQL"},"junk"]
        entries=terminal.build_command_index(rows)
        self.assertEqual(["nmap {IPv4}","Get-Process","dir","select 1"],[e["command"] for e in entries])
        self.assertEqual(["posix","powershell","cmd","any"],[e["family"] for e in entries])
        self.assertEqual("Scan",entries[0]["title"])
    def test_index_reads_saved_commands_and_reports_unchanged(self):
        from Cores.Services import commands_service as cmds
        cmds._insert_cmd(cmds._db_path(),"Recon","Network","Scan","nmap -sV {IPv4}","","","Linux Shell","normal")
        first=terminal.command_index()
        self.assertIn("nmap -sV {IPv4}",[e["command"] for e in first["entries"]])
        again=terminal.command_index(first["sig"])
        self.assertTrue(again.get("unchanged"))
        cmds._insert_cmd(cmds._db_path(),"Recon","Web","Dirs","gobuster dir -u {URL}","","","other","normal")
        changed=terminal.command_index(first["sig"])
        self.assertFalse(changed.get("unchanged",False))
        self.assertIn("gobuster dir -u {URL}",[e["command"] for e in changed["entries"]])
if __name__=="__main__":unittest.main()
