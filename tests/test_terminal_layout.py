import unittest
from _isolate import IsolatedData
from Cores.Services import terminal_service as terminal
class PanelLayoutTests(unittest.TestCase):
    def setUp(self):
        self.isolated=IsolatedData()
        self.isolated.start()
    def tearDown(self):
        self.isolated.stop()
    def test_defaults_are_right_dock_not_maximized(self):
        settings=terminal.get_settings()
        self.assertEqual("right",settings["panel_mode"])
        self.assertEqual(380,settings["panel_width"])
        self.assertEqual(320,settings["panel_height"])
        self.assertFalse(settings["panel_maximized"])
    def test_each_mode_round_trips(self):
        for mode in ("left","bottom","right"):
            terminal.set_panel_layout({"mode":mode})
            self.assertEqual(mode,terminal.get_settings()["panel_mode"])
    def test_unknown_mode_is_ignored(self):
        terminal.set_panel_layout({"mode":"bottom"})
        terminal.set_panel_layout({"mode":"diagonal"})
        self.assertEqual("bottom",terminal.get_settings()["panel_mode"])
    def test_width_and_height_are_clamped(self):
        terminal.set_panel_layout({"width":10,"height":10})
        settings=terminal.get_settings()
        self.assertEqual(260,settings["panel_width"])
        self.assertEqual(160,settings["panel_height"])
        terminal.set_panel_layout({"width":99999,"height":99999})
        settings=terminal.get_settings()
        self.assertEqual(900,settings["panel_width"])
        self.assertEqual(1200,settings["panel_height"])
    def test_garbage_sizes_fall_back_to_defaults(self):
        terminal.set_panel_layout({"width":"wide","height":None})
        settings=terminal.get_settings()
        self.assertEqual(380,settings["panel_width"])
        self.assertEqual(320,settings["panel_height"])
    def test_partial_update_leaves_other_keys_alone(self):
        terminal.set_panel_layout({"mode":"bottom","width":500,"height":400,"maximized":True})
        terminal.set_panel_layout({"width":600})
        settings=terminal.get_settings()
        self.assertEqual("bottom",settings["panel_mode"])
        self.assertEqual(600,settings["panel_width"])
        self.assertEqual(400,settings["panel_height"])
        self.assertTrue(settings["panel_maximized"])
    def test_maximized_round_trips(self):
        terminal.set_panel_layout({"maximized":True})
        self.assertTrue(terminal.get_settings()["panel_maximized"])
        terminal.set_panel_layout({"maximized":False})
        self.assertFalse(terminal.get_settings()["panel_maximized"])
    def test_font_size_defaults_round_trips_and_clamps(self):
        self.assertEqual(12,terminal.get_settings()["font_size"])
        terminal.set_panel_layout({"font_size":15})
        self.assertEqual(15,terminal.get_settings()["font_size"])
        terminal.set_panel_layout({"font_size":3})
        self.assertEqual(9,terminal.get_settings()["font_size"])
        terminal.set_panel_layout({"font_size":99})
        self.assertEqual(22,terminal.get_settings()["font_size"])
        terminal.set_panel_layout({"font_size":"huge"})
        self.assertEqual(12,terminal.get_settings()["font_size"])
        terminal.set_panel_layout({"mode":"bottom"})
        self.assertEqual(12,terminal.get_settings()["font_size"])
    def test_legacy_width_setter_still_works(self):
        terminal.set_panel_width(500)
        self.assertEqual(500,terminal.get_settings()["panel_width"])
        terminal.set_panel_width(10)
        self.assertEqual(260,terminal.get_settings()["panel_width"])
    def test_layout_survives_run_behaviour_writes(self):
        terminal.set_panel_layout({"mode":"left","width":700})
        terminal.set_run_behaviour({"snippet_click_action":"run"})
        settings=terminal.get_settings()
        self.assertEqual("left",settings["panel_mode"])
        self.assertEqual(700,settings["panel_width"])
    def test_non_dict_payload_is_harmless(self):
        terminal.set_panel_layout({"mode":"left"})
        terminal.set_panel_layout(None)
        self.assertEqual("left",terminal.get_settings()["panel_mode"])
if __name__=="__main__":unittest.main()
