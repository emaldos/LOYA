import unittest
from _isolate import IsolatedData
from Cores.Services import ai_service as ai
class AIPanelLayoutTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
    def tearDown(self):
        self.isolated.stop()
    def test_defaults_are_left_dock(self):
        settings=ai.get_settings()
        self.assertEqual("left",settings["panel_mode"])
        self.assertEqual(380,settings["panel_width"])
        self.assertEqual(320,settings["panel_height"])
    def test_each_mode_round_trips(self):
        for mode in ("right","bottom","left"):
            ai.set_panel_layout({"mode":mode})
            self.assertEqual(mode,ai.get_settings()["panel_mode"])
    def test_unknown_mode_and_garbage_are_ignored(self):
        ai.set_panel_layout({"mode":"bottom"})
        ai.set_panel_layout({"mode":"diagonal"})
        ai.set_panel_layout(None)
        self.assertEqual("bottom",ai.get_settings()["panel_mode"])
    def test_sizes_are_clamped(self):
        ai.set_panel_layout({"height":10,"width":10})
        settings=ai.get_settings()
        self.assertEqual(160,settings["panel_height"])
        self.assertEqual(260,settings["panel_width"])
        ai.set_panel_layout({"height":99999})
        self.assertEqual(1200,ai.get_settings()["panel_height"])
    def test_layout_does_not_touch_enabled_or_width(self):
        ai.set_enabled(False)
        ai.set_panel_width(500)
        ai.set_panel_layout({"mode":"right","height":400})
        settings=ai.get_settings()
        self.assertFalse(settings["enabled"])
        self.assertEqual(500,settings["panel_width"])
        self.assertEqual(400,settings["panel_height"])
if __name__=="__main__":unittest.main()
