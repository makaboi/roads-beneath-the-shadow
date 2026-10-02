"""Fullscreen lifecycle regressions using real SDL surfaces and pending input."""

import importlib.util
import os
import threading
import time
import unittest
import warnings
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from roads_beneath_shadow.pixel_ui import PixelUI, PixelWindow
from roads_beneath_shadow.ui import InputClosed


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for display lifecycle tests")
class PixelDisplayLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.ui = PixelUI(fast=True, sound=False)
        self.window = PixelWindow(self.ui, size=(1200, 900))
        self.pg = self.window.pg
        self.worker = None
        self.answers = []

    def tearDown(self):
        self.ui.close()
        if self.worker is not None:
            self.worker.join(timeout=1)
            self.assertFalse(self.worker.is_alive())
        self.pg.quit()

    def start(self, method):
        def run():
            try:
                self.answers.append(method())
            except InputClosed:
                pass

        self.worker = threading.Thread(target=run)
        self.worker.start()
        deadline = time.monotonic() + 2
        while self.window.request is None and time.monotonic() < deadline:
            self.window.drain()
            time.sleep(0.002)
        self.assertIsNotNone(self.window.request)
        self.settle()

    def key(self, code):
        self.window.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=code, unicode="", mod=0))

    def settle(self):
        # Native window managers complete their decoration/geometry changes
        # asynchronously. Also exercise events fetched before the next frame.
        duration = 0.15 if self.pg.display.get_driver() != "dummy" else 0.01
        deadline = time.monotonic() + duration
        while time.monotonic() < deadline:
            for event in self.pg.event.get():
                self.window.handle_event(event)
            self.window.render()
            time.sleep(0.002)

    def resize_event(self, size):
        self.window.handle_event(self.pg.event.Event(self.pg.VIDEORESIZE, size=size, w=size[0], h=size[1]))

    def test_repeated_fullscreen_restores_size_position_and_pending_name(self):
        self.start(lambda: self.ui.prompt("Traveler's name: "))
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Éowen"))
        request = self.window.request
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            for requested_position in ((350, 250), (-100, 90), (220, 180)):
                self.pg.display.set_window_position(requested_position)
                self.settle()
                original_position = self.pg.display.get_window_position()
                original_size = self.window.screen.get_size()
                self.key(self.pg.K_F11)
                self.settle()
                fullscreen_size = self.window.screen.get_size()
                self.assertTrue(self.window.fullscreen)
                self.key(self.pg.K_F11)
                self.settle()
                self.assertFalse(self.window.fullscreen)
                self.assertEqual(self.pg.display.get_window_size(), original_size)
                self.assertEqual(self.window.screen.get_size(), original_size)
                self.assertEqual(self.window.window_size, original_size)
                self.assertEqual(self.pg.display.get_window_position(), original_position)
                # A restoration acknowledgement followed by an old fullscreen
                # event must still preserve the window and pending request.
                self.resize_event(original_size)
                self.resize_event(fullscreen_size)
                self.window.render()
                self.assertEqual(self.window.screen.get_size(), original_size)
                self.assertEqual(self.window.window_size, original_size)
                self.assertEqual(self.pg.display.get_window_position(), original_position)
                self.assertIs(self.window.request, request)
                self.assertEqual(self.window.entry, "Éowen")
                self.assertTrue(self.worker.is_alive())
                self.assertEqual(self.answers, [])
        self.assertFalse(any("forcibly resized" in str(item.message) for item in caught))
        self.key(self.pg.K_RETURN)
        self.worker.join(timeout=1)
        self.assertEqual(self.answers, ["Éowen"])

    def test_genuine_resize_after_fullscreen_becomes_the_next_restore_size(self):
        self.start(lambda: self.ui.choose_story("Which road?", ["Follow the lantern", "Wait"]))
        request = self.window.request
        self.key(self.pg.K_F11)
        self.settle()
        self.key(self.pg.K_F11)
        self.settle()
        # An actual window resize changes SDL geometry before notification.
        # This works with the real X11 backend and with headless SDL in CI.
        resized = (980, 700)
        self.pg.display.set_mode(resized, self.pg.RESIZABLE)
        self.resize_event(resized)
        self.settle()
        self.assertEqual(self.window.window_size, resized)
        self.key(self.pg.K_F11)
        self.settle()
        self.key(self.pg.K_F11)
        self.settle()
        self.assertEqual(self.pg.display.get_window_size(), resized)
        self.assertEqual(self.window.screen.get_size(), resized)
        self.assertIs(self.window.request, request)
        self.assertTrue(self.worker.is_alive())
        self.assertEqual(self.answers, [])

    def test_unsupported_native_toggle_does_not_close_or_answer_the_story(self):
        self.start(lambda: self.ui.choose_story("Which road?", ["Follow the lantern", "Wait"]))
        self.key(self.pg.K_F11)
        self.settle()
        request = self.window.request
        restore_size = self.window.window_size
        with patch.object(self.pg.display, "get_driver", return_value="x11"), patch.object(
            self.pg.display, "toggle_fullscreen", side_effect=self.pg.error("Unsupported platform")
        ):
            self.key(self.pg.K_F11)
        self.assertTrue(self.window.fullscreen)
        self.assertEqual(self.window.window_size, restore_size)
        self.assertIs(self.window.request, request)
        self.assertFalse(self.ui.closed.is_set())
        self.assertEqual(self.answers, [])
        self.assertIn("could not change fullscreen", self.window._toasts[-1][0])
        self.key(self.pg.K_F11)
        self.settle()
        self.assertFalse(self.window.fullscreen)
        self.assertEqual(self.window.screen.get_size(), restore_size)

    def test_unavailable_window_position_read_still_restores_pending_name(self):
        self.start(lambda: self.ui.prompt("Traveler's name: "))
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Éowen"))
        request = self.window.request
        size = self.window.screen.get_size()
        with patch.object(self.pg.display, "get_window_position", side_effect=self.pg.error("Unsupported driver")) as position_read:
            self.key(self.pg.K_F11)
            self.settle()
        position_read.assert_called_once()
        self.assertTrue(self.window.fullscreen)
        self.key(self.pg.K_F11)
        self.settle()
        self.assertFalse(self.window.fullscreen)
        self.assertEqual(self.window.screen.get_size(), size)
        self.assertIs(self.window.request, request)
        self.assertEqual(self.window.entry, "Éowen")
        self.assertTrue(self.worker.is_alive())
        self.assertEqual(self.answers, [])
        self.assertFalse(self.ui.closed.is_set())

    def test_unavailable_window_position_restore_keeps_pending_choice(self):
        self.start(lambda: self.ui.choose_story("Which road?", ["Follow the lantern", "Wait"]))
        request = self.window.request
        size = self.window.screen.get_size()
        self.key(self.pg.K_F11)
        self.settle()
        with patch.object(self.pg.display, "set_window_position", side_effect=self.pg.error("Unsupported driver")) as position_restore:
            self.key(self.pg.K_F11)
            self.settle()
        position_restore.assert_called_once()
        self.assertFalse(self.window.fullscreen)
        self.assertEqual(self.window.screen.get_size(), size)
        self.assertIs(self.window.request, request)
        self.assertTrue(self.worker.is_alive())
        self.assertEqual(self.answers, [])
        self.assertFalse(self.ui.closed.is_set())


if __name__ == "__main__":
    unittest.main()
