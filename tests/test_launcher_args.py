import unittest
from _isolate import ROOT
import RunNote
class LauncherArgTests(unittest.TestCase):
    # --version and --help used to be ignored, so they started the app instead of answering.
    def test_informational_flags_are_recognised(self):
        self.assertTrue(RunNote._parse_args(["--version"])["version"])
        self.assertTrue(RunNote._parse_args(["-V"])["version"])
        self.assertTrue(RunNote._parse_args(["--help"])["help"])
        self.assertTrue(RunNote._parse_args(["-h"])["help"])
    def test_existing_flags_still_work(self):
        a=RunNote._parse_args(["--skip-update","--verbose","--recovery","--reason","broken update"])
        self.assertTrue(a["skip_update"]);self.assertTrue(a["verbose"]);self.assertTrue(a["force_recovery"])
        self.assertEqual("broken update",a["recovery_reason"])
        self.assertFalse(a["version"]);self.assertFalse(a["help"]);self.assertEqual([],a["unknown"])
    def test_unknown_flags_are_collected_not_fatal(self):
        self.assertEqual(["--bogus"],RunNote._parse_args(["--bogus","--verbose"])["unknown"])
    def test_usage_lists_every_option(self):
        for opt in ("--skip-update","--verbose","--recovery","--reason","--version","--help"):
            self.assertIn(opt,RunNote._USAGE)
if __name__=="__main__":unittest.main()
