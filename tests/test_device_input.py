"""Physical press/release contracts independent of HTTP, UI and game state."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from esp32_runtime.input import GestureInput


class DeviceInputContracts(unittest.TestCase):
    def setUp(self):
        self.g = GestureInput(clock=lambda: 0.)

    def feed(self, phase, key=None, at=0., **kwargs):
        return self.g.feed(phase, key, now=at, **kwargs)

    def test_short_click_only_on_release_and_os_repeat_is_ignored(self):
        self.assertEqual(self.feed("down", "A"), [])
        self.assertEqual(self.feed("down", "A", .1), [])
        self.assertEqual(self.feed("up", "A", .2), [("click", "A")])
        self.assertEqual(self.feed("up", "A", .3), [])

    def test_back_and_detail_fire_at_600ms_without_release_click(self):
        for key, action in (("B", "back"), ("C", "detail")):
            g = GestureInput(clock=lambda: 0.)
            g.feed("down", key, now=0.)
            self.assertEqual(g.feed("tick", now=.599), [])
            self.assertEqual(g.feed("tick", now=.6), [(action, key)])
            self.assertEqual(g.feed("tick", now=.7), [])
            self.assertEqual(g.feed("up", key, now=.8), [])

    def test_c_detail_can_continue_to_global_sleep_despite_page_transition(self):
        self.feed("down", "C")
        self.assertEqual(self.feed("tick", at=.6), [("detail", "C")])
        self.g.block(.6)
        self.assertEqual(self.feed("tick", at=1.499), [])
        self.assertEqual(self.feed("tick", at=1.5), [("sleep", "C")])
        self.assertTrue(self.g.sleeping)
        self.assertEqual(self.feed("up", "C", 1.7), [])

    def test_release_computes_long_hold_without_tick_and_no_short_action(self):
        self.feed("down", "B")
        self.assertEqual(self.feed("up", "B", .7), [("back", "B")])
        self.feed("down", "C", 1.)
        self.assertEqual(self.feed("up", "C", 2.6), [("sleep", "C")])

    def test_wake_swallows_whole_gesture_and_chord_until_end(self):
        self.g.sleeping = True
        self.assertEqual(self.feed("down", "C"), [("wake", "C")])
        self.assertEqual(self.feed("down", "B", .1), [])
        self.assertEqual(self.feed("tick", at=2.), [])
        self.assertEqual(self.feed("up", "C", 2.1), [])
        self.assertEqual(self.feed("up", "B", 2.2), [])
        self.feed("down", "C", 2.3)
        self.assertEqual(self.feed("up", "C", 2.4), [("click", "C")])

    def test_cancel_and_busy_drain_held_keys_without_click(self):
        self.feed("down", "C")
        self.assertEqual(self.feed("cancel", at=.1), [])
        self.assertEqual(self.feed("up", "C", .15), [])
        self.feed("down", "A", .3, busy=True)
        self.assertEqual(self.feed("up", "A", .4), [])
        self.feed("down", "C", .5)
        self.assertEqual(self.feed("tick", at=2., busy=True), [])
        self.assertEqual(self.feed("up", "C", 2.1), [])

    def test_transition_swallows_new_hold_even_after_block_period_ends(self):
        self.g.block(0.)
        self.feed("down", "C", .05)
        self.assertEqual(self.feed("up", "C", .2), [])
        self.feed("down", "A", .3)
        self.assertEqual(self.feed("up", "A", .4), [("click", "A")])

    def test_idle_sleep_and_bad_clock_or_unknown_key(self):
        self.assertEqual(self.feed("tick", at=60.), [("sleep", None)])
        for phase, key, at in (("click", "C", 61.), ("down", "D", 61.), ("tick", None, 59.), ("tick", None, float("nan"))):
            with self.subTest(phase=phase, key=key, at=at), self.assertRaises(ValueError):
                self.feed(phase, key, at)


if __name__ == "__main__":
    unittest.main()
