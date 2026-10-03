"""Changing a setting keeps that actual control visible in the next request."""

from __future__ import annotations

import importlib.util
import threading
import unittest
from unittest.mock import patch

from tests import test_pixel_controls as journey_controls
from roads_beneath_shadow.ui import InputClosed


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for settings navigation")
class SettingsNavigationTests(unittest.TestCase):
    setUp = journey_controls.JourneyControlsTests.setUp
    tearDown = journey_controls.JourneyControlsTests.tearDown
    await_request = journey_controls.JourneyControlsTests.await_request
    key = journey_controls.JourneyControlsTests.key

    def begin_settings(self, *, size=(760, 560), text_size="larger"):
        self.game.user_settings.text_size = text_size
        self.ui.text_size = text_size
        self.pg.display.set_mode(size, self.pg.RESIZABLE)
        self.window.handle_event(self.pg.event.Event(self.pg.VIDEORESIZE, w=size[0], h=size[1]))

        def run():
            try:
                self.game._settings()
            except InputClosed:
                pass
            except Exception as error:
                self.errors.append(error)

        self.worker = threading.Thread(target=run)
        self.worker.start()
        return self.await_request(lambda request: request.context.get("navigation_group") == "settings")

    def select_control(self, index):
        for _ in range(index):
            self.key(self.pg.K_DOWN)
        self.window.render()
        self.assertEqual(self.window.selected, index)

    def adjust(self):
        previous = self.window.request.identifier
        self.key(self.pg.K_RETURN)
        return self.await_request(lambda request: request.identifier != previous
                                  and request.context.get("navigation_group") == "settings")

    def assert_selection_visible(self):
        dimensions = self.window._choice_dimensions()
        top = sum(height + 10 for height, _ in dimensions[:self.window.selected])
        bottom = top + dimensions[self.window.selected][0]
        self.assertGreaterEqual(top - self.window.choice_scroll, 0)
        self.assertLessEqual(bottom - self.window.choice_scroll, self.window.menu_rect.height)

    def test_repeated_volume_adjustments_keep_the_control_and_entire_journey(self):
        before = self.game.state.to_dict()
        self.begin_settings()
        self.select_control(6)
        self.assertGreater(self.window.choice_scroll, 0)
        for expected in (0.5, 0.75, 1.0, 0.0, 0.25):
            self.adjust()
            self.assertEqual(self.game.user_settings.music_volume, expected)
            self.assertEqual(self.window.selected, 6)
            self.assert_selection_visible()
            self.assertEqual(self.game.state.to_dict(), before)

    def test_reading_size_changes_refit_the_same_control_after_fonts_change(self):
        self.begin_settings(text_size="standard")
        self.select_control(9)
        for expected in ("large", "larger", "standard"):
            self.adjust()
            self.assertEqual(self.ui.text_size, expected)
            self.assertEqual(self.window.selected, 9)
            self.assert_selection_visible()

    def test_back_ends_the_settings_visit_and_a_new_visit_starts_at_top(self):
        self.begin_settings()
        self.select_control(7)
        self.adjust()
        self.key(self.pg.K_ESCAPE)
        self.worker.join(1)
        self.assertFalse(self.worker.is_alive())
        self.assertIsNone(self.window._settings_navigation)
        self.begin_settings()
        self.assertEqual(self.window.selected, 0)
        self.assertEqual(self.window.choice_scroll, 0)

    def test_wheel_browsing_is_not_pulled_back_to_the_keyboard_selection(self):
        self.begin_settings()
        self.select_control(6)
        self.adjust()
        before = self.window.choice_scroll
        for _ in range(5):
            self.window.render()
        self.assertEqual(self.window.choice_scroll, before)
        with patch.object(self.pg.mouse, "get_pos", return_value=self.window.menu_rect.center):
            self.window.handle_event(self.pg.event.Event(self.pg.MOUSEWHEEL, y=1, x=0))
        requested = max(0, before - 55)
        self.assertEqual(self.window.choice_scroll, requested)
        self.window.render()
        self.assertEqual(self.window.choice_scroll, requested)


if __name__ == "__main__":
    unittest.main()
