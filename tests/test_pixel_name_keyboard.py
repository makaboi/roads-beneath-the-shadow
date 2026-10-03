"""The optional naming keyboard shares the pending Unicode text request."""

from __future__ import annotations

import importlib.util
import threading
import unittest

from tests import test_pixel_controls as journey_controls
from roads_beneath_shadow.ui import InputClosed


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for the naming keyboard")
class NameKeyboardWindowTests(unittest.TestCase):
    setUp = journey_controls.JourneyControlsTests.setUp
    tearDown = journey_controls.JourneyControlsTests.tearDown
    await_request = journey_controls.JourneyControlsTests.await_request
    key = journey_controls.JourneyControlsTests.key

    def start_name(self, *, size=(760, 560)):
        self.pg.display.set_mode(size, self.pg.RESIZABLE)
        self.window.handle_event(self.pg.event.Event(self.pg.VIDEORESIZE, w=size[0], h=size[1]))
        self.ui.text_size = "larger"

        def run():
            try:
                self.results.append(self.ui.choose_name("Traveler's name: "))
            except InputClosed:
                pass
            except Exception as error:
                self.errors.append(error)

        self.worker = threading.Thread(target=run)
        self.worker.start()
        return self.await_request(lambda request: request.kind == "text")

    def click(self, position):
        self.window.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=position))
        self.window.render()

    def open_keyboard(self):
        self.click(self.window._name_keyboard_hit.center)
        self.assertTrue(self.window.name_keyboard.active)

    def click_key(self, row, column):
        rect = next(rect for rect, position in self.window.name_keyboard.hit_targets
                    if position == (row, column))
        self.click(rect.center)

    def test_mouse_naming_uses_the_same_editor_and_submits_once(self):
        request = self.start_name()
        before = self.game.state.to_dict()
        self.open_keyboard()
        self.assertIs(self.window.request, request)
        self.click_key(4, 0)  # Uppercase.
        self.click_key(2, 6)  # M.
        self.click_key(4, 0)  # Lowercase.
        for row, column in ((0, 7), (0, 3), (1, 0)):
            self.click_key(row, column)
        self.assertEqual(self.window.entry, "Mira")
        self.assertEqual(self.results, [])
        self.assertEqual(self.game.state.to_dict(), before)
        self.click_key(4, 3)  # Done.
        self.worker.join(1)
        self.assertFalse(self.worker.is_alive())
        self.assertEqual(self.results, ["Mira"])
        self.assertFalse(self.window.name_keyboard.active)

    def test_blank_done_and_first_back_do_not_cancel_creation(self):
        request = self.start_name()
        self.open_keyboard()
        self.click_key(4, 3)
        self.assertEqual(self.results, [])
        self.assertIs(self.window.request, request)
        self.key(self.pg.K_ESCAPE)
        self.assertFalse(self.window.name_keyboard.active)
        self.assertIs(self.window.request, request)
        self.assertTrue(self.worker.is_alive())
        self.key(self.pg.K_ESCAPE)
        self.worker.join(1)
        self.assertEqual(self.results, [None])

    def test_physical_unicode_and_selection_work_inside_the_keyboard(self):
        self.start_name()
        self.open_keyboard()
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Mira"))
        self.window.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_a,
                                                    unicode="", mod=self.pg.KMOD_CTRL))
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Éowen"))
        self.window.render()
        self.assertEqual(self.window.entry, "Éowen")
        self.click_key(4, 3)
        self.worker.join(1)
        self.assertEqual(self.results, ["Éowen"])

    def test_uncommitted_composition_cannot_be_deleted_or_submitted_by_virtual_keys(self):
        request = self.start_name()
        self.open_keyboard()
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Mira"))
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTEDITING, text="Éowen", start=0, length=5))
        self.window.render()
        self.click_key(2, 6)
        self.click_key(4, 2)
        self.click_key(4, 3)
        self.assertIs(self.window.request, request)
        self.assertEqual(self.window.entry, "Mira")
        self.assertEqual(self.window.entry_composition, "Éowen")
        self.assertEqual(self.results, [])
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Éowen"))
        self.window.render()
        self.click_key(4, 3)
        self.worker.join(1)
        self.assertEqual(self.results, ["MiraÉowen"])

    def test_pointer_modal_and_fullscreen_preserve_the_name_and_editor_limit(self):
        request = self.start_name()
        self.open_keyboard()
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="É" * 24))
        self.window.render()
        self.click_key(0, 0)
        self.assertEqual(self.window.entry, "É" * 24)
        self.click((1, 1))
        self.assertIs(self.window.request, request)
        self.assertEqual(self.results, [])
        selected = self.window.name_keyboard.selected_key
        self.key(self.pg.K_F11)
        self.window.render()
        self.key(self.pg.K_F11)
        self.window.render()
        self.assertTrue(self.window.name_keyboard.active)
        self.assertEqual(self.window.name_keyboard.selected_key, selected)
        self.assertEqual(self.window.entry, "É" * 24)
        self.assertEqual(len(self.window.name_keyboard.hit_targets), 41)
        self.assertTrue(all(self.window.screen.get_rect().contains(rect)
                            for rect, _ in self.window.name_keyboard.hit_targets))

    def test_opening_controls_closes_keyboard_without_answering_name(self):
        request = self.start_name()
        self.open_keyboard()
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Éowen"))
        self.key(self.pg.K_F1)
        self.assertFalse(self.window.name_keyboard.active)
        self.assertTrue(self.window.panels.active)
        self.key(self.pg.K_ESCAPE)
        self.window.render()
        self.assertFalse(self.window.panels.active)
        self.assertIs(self.window.request, request)
        self.assertEqual(self.window.entry, "Éowen")
        self.assertEqual(self.results, [])


if __name__ == "__main__":
    unittest.main()
