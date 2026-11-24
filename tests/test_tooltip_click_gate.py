import unittest
from unittest import mock
from _isolate import ROOT
try:
    from Cores.Bridge import api
except Exception:
    api=None
@unittest.skipIf(api is None,"Cores.Bridge.api not importable")
class TooltipClickGateTests(unittest.TestCase):
    """WebKitGTK re-showed a clicked button's title over the popover it opened; tooltips now wait for real pointer motion."""
    def test_tooltips_allowed_before_any_click(self):
        self.assertTrue(api._TooltipClickGate().allow())
    def test_click_blocks_until_the_pointer_moves(self):
        g=api._TooltipClickGate()
        g.press(100,40)
        self.assertFalse(g.allow())
        g.motion(102,41)
        self.assertFalse(g.allow(),"jitter within the slop must not bring the tooltip back")
        g.motion(110,40)
        self.assertTrue(g.allow())
    def test_motion_without_click_changes_nothing(self):
        g=api._TooltipClickGate()
        g.motion(5,5)
        self.assertTrue(g.allow())
    def test_scroll_or_typing_hides_until_the_pointer_moves(self):
        g=api._TooltipClickGate()
        g.motion(200,80)
        g.hold()
        self.assertFalse(g.allow(),"the element under a still pointer may have changed")
        g.motion(201,80)
        self.assertFalse(g.allow())
        g.motion(210,80)
        self.assertTrue(g.allow())
    def test_hold_before_any_motion_clears_on_the_first_motion(self):
        g=api._TooltipClickGate()
        g.hold()
        self.assertFalse(g.allow())
        g.motion(0,0)
        self.assertTrue(g.allow())
    def test_scroll_and_key_presses_are_wired(self):
        src=open(api.__file__,encoding="utf-8").read()
        self.assertIn('wv.connect("scroll-event",on_hold);wv.connect("key-press-event",on_hold)',src)
    def test_install_is_linux_only_and_safe_without_a_view(self):
        with mock.patch.object(api,"_IS_LINUX",False):
            self.assertFalse(api._install_tooltip_click_hide(object()))
        with mock.patch.object(api,"_IS_LINUX",True),mock.patch.object(api,"_gtk_view",return_value=None):
            self.assertFalse(api._install_tooltip_click_hide(object()))
    def test_both_windows_install_it(self):
        src=open(api.__file__,encoding="utf-8").read()
        self.assertEqual(2,src.count("window.events.shown+=lambda:_install_tooltip_click_hide(window)"))
if __name__=="__main__":
    unittest.main()
