"""Acknowledge SDL's live surface without issuing another native resize."""

import importlib.util
import unittest
from unittest.mock import patch

from tests import test_pixel_display as display_lifecycle


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for display lifecycle tests")
class PixelResizeLifecycleTests(unittest.TestCase):
    # Reuse the real display/pending-worker setup, without inheriting its tests.
    setUp = display_lifecycle.PixelDisplayLifecycleTests.setUp
    tearDown = display_lifecycle.PixelDisplayLifecycleTests.tearDown
    start = display_lifecycle.PixelDisplayLifecycleTests.start
    key = display_lifecycle.PixelDisplayLifecycleTests.key
    settle = display_lifecycle.PixelDisplayLifecycleTests.settle
    resize_event = display_lifecycle.PixelDisplayLifecycleTests.resize_event

    def pending_name(self):
        self.start(lambda: self.ui.prompt("Traveler's name: "))
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Éowen"))
        return self.window.request

    def assert_pending_name(self, request):
        self.assertIs(self.window.request, request)
        self.assertEqual(self.window.entry, "Éowen")
        self.assertTrue(self.worker.is_alive())
        self.assertEqual(self.answers, [])
        self.assertFalse(self.ui.closed.is_set())

    def native_resize(self, size):
        # SDL has already applied a native resize when VIDEORESIZE is handled.
        # Create that real surface before the event, then count only the
        # renderer's acknowledgement. Both dummy and real X11 use SDL surfaces.
        self.pg.display.set_mode(size, self.pg.RESIZABLE)
        self.window._restoring_window_size = None
        return self.pg.display.get_surface()

    def test_live_resized_surface_is_acknowledged_without_another_set_mode(self):
        request = self.pending_name()
        surface = self.native_resize((980, 700))
        with patch.object(self.pg.display, "set_mode", wraps=self.pg.display.set_mode) as set_mode:
            self.resize_event((980, 700))
            self.window.render()
        set_mode.assert_not_called()
        self.assertIs(self.window.screen, surface)
        self.assertEqual(self.window.window_size, (980, 700))
        self.assertEqual(self.pg.display.get_window_size(), (980, 700))
        self.assert_pending_name(request)

    def test_stale_queued_resize_uses_current_surface_dimensions(self):
        request = self.pending_name()
        surface = self.native_resize((1120, 780))
        with patch.object(self.pg.display, "set_mode", wraps=self.pg.display.set_mode) as set_mode:
            # Both events were fetched before SDL applied the latest size.
            self.resize_event((980, 700))
            self.resize_event((760, 560))
            self.window.render()
        set_mode.assert_not_called()
        self.assertIs(self.window.screen, surface)
        self.assertEqual(self.window.screen.get_size(), (1120, 780))
        self.assertEqual(self.window.window_size, (1120, 780))
        self.assertEqual(self.pg.display.get_window_size(), (1120, 780))
        self.assert_pending_name(request)

    def test_below_minimum_native_resize_is_corrected_once(self):
        request = self.pending_name()
        self.native_resize((500, 360))
        with patch.object(self.pg.display, "set_mode", wraps=self.pg.display.set_mode) as set_mode:
            self.resize_event((500, 360))
            self.resize_event((500, 360))
            self.resize_event((760, 560))
            self.window.render()
        set_mode.assert_called_once_with((760, 560), self.pg.RESIZABLE)
        self.assertEqual(self.window.screen.get_size(), (760, 560))
        self.assertEqual(self.window.window_size, (760, 560))
        self.assertEqual(self.pg.display.get_window_size(), (760, 560))
        self.assert_pending_name(request)

    def test_native_drag_after_fullscreen_keeps_latest_size_when_old_event_follows(self):
        request = self.pending_name()
        self.key(self.pg.K_F11)
        self.settle()
        fullscreen_size = self.window.screen.get_size()
        self.key(self.pg.K_F11)
        self.settle()
        self.assertIsNotNone(self.window._restoring_window_size)
        self.pg.display.set_mode((980, 700), self.pg.RESIZABLE)
        surface = self.pg.display.get_surface()
        with patch.object(self.pg.display, "set_mode", wraps=self.pg.display.set_mode) as set_mode:
            self.resize_event((980, 700))
            self.resize_event(fullscreen_size)
            self.window.render()
        set_mode.assert_not_called()
        self.assertIsNone(self.window._restoring_window_size)
        self.assertIs(self.window.screen, surface)
        self.assertEqual(self.window.window_size, (980, 700))
        self.assertEqual(self.pg.display.get_window_size(), (980, 700))
        self.assert_pending_name(request)


if __name__ == "__main__":
    unittest.main()
