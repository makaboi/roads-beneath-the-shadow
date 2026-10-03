"""Minimizing preserves pending input and stops invisible presentation work."""

import importlib.util
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.pixel_ui import PixelUI, PixelWindow, launch_pixel_game
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.settings import SettingsManager
from tests import test_pixel_display as display_fixtures
from tests import test_pixel_controls as story_fixtures
from tests import test_pixel_controller_integration as controller_fixtures


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for minimized windows")
class MinimizedNameTests(unittest.TestCase):
    setUp = display_fixtures.PixelDisplayLifecycleTests.setUp
    tearDown = display_fixtures.PixelDisplayLifecycleTests.tearDown
    start = display_fixtures.PixelDisplayLifecycleTests.start
    settle = display_fixtures.PixelDisplayLifecycleTests.settle

    def test_hidden_window_does_not_draw_edit_or_submit_the_pending_name(self):
        self.start(lambda: self.ui.choose_name())
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Eowen旅"))
        self.window.render()
        request = self.window.request
        self.window.handle_event(self.pg.event.Event(self.pg.WINDOWMINIMIZED))
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="hidden"))
        self.window.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_RETURN, unicode="", mod=0))
        with patch.object(self.pg.display, "flip", wraps=self.pg.display.flip) as flip:
            self.window.render()
        flip.assert_not_called()
        self.assertEqual(self.window.entry, "Eowen旅")
        self.assertIs(self.window.request, request)
        self.assertTrue(self.worker.is_alive())
        self.assertEqual(self.answers, [])
        self.window.handle_event(self.pg.event.Event(self.pg.WINDOWRESTORED))
        self.window.render()
        self.window.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_RETURN, unicode="", mod=0))
        self.worker.join(1)
        self.assertFalse(self.worker.is_alive())
        self.assertEqual(self.answers, ["Eowen旅"])

    def test_restore_keeps_remaining_notice_time_and_new_hidden_notices_bounded(self):
        self.start(lambda: self.ui.choose_name())
        start = self.pg.time.get_ticks()
        with patch.object(self.pg.time, "get_ticks", return_value=start):
            self.window._toast("Already waiting")
            self.window._toasts_deferred = True
            self.window.handle_event(self.pg.event.Event(self.pg.WINDOWMINIMIZED))
        with patch.object(self.pg.time, "get_ticks", return_value=start + 30_000):
            self.ui.toast("Arrived while hidden")
            self.window.drain()
            self.window.handle_event(self.pg.event.Event(self.pg.WINDOWMINIMIZED))
        with patch.object(self.pg.time, "get_ticks", return_value=start + 60_000):
            self.window.handle_event(self.pg.event.Event(self.pg.WINDOWRESTORED))
            self.window.render()
        self.assertEqual([text for text, _ in self.window._toasts],
                         ["Already waiting", "Arrived while hidden"])
        for _, expiry in self.window._toasts:
            self.assertAlmostEqual(expiry - (start + 60_000) / 1000, 4.0)


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for minimized windows")
class MinimizedStoryTests(unittest.TestCase):
    setUp = story_fixtures.JourneyControlsTests.setUp
    tearDown = story_fixtures.JourneyControlsTests.tearDown
    start = story_fixtures.JourneyControlsTests.start
    await_request = story_fixtures.JourneyControlsTests.await_request

    def test_restore_resumes_the_same_reveal_without_counting_hidden_minutes(self):
        self.ui.set_text_speed("normal")
        self.ui.narrate(" ".join(f"memory{index}" for index in range(100)))
        self.start()
        self.window._page_reveal = 23.0
        request, page = self.window.request, self.window.narrative.current
        state = self.game.state.to_dict()
        self.window.handle_event(self.pg.event.Event(self.pg.WINDOWMINIMIZED))
        future = self.pg.time.get_ticks() + 60_000
        with patch.object(self.pg.time, "get_ticks", return_value=future):
            self.window.render()
            self.window.handle_event(self.pg.event.Event(self.pg.WINDOWRESTORED))
            self.window.render()
        self.assertEqual(self.window._page_reveal, 23.0)
        self.assertIs(self.window.narrative.current, page)
        self.assertIs(self.window.request, request)
        self.assertEqual(self.game.state.to_dict(), state)
        self.assertTrue(self.worker.is_alive())
        self.assertEqual(self.results, [])


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for minimized windows")
class MinimizedControllerTests(unittest.TestCase):
    setUp = controller_fixtures.ControllerWindowIntegrationTests.setUp
    tearDown = controller_fixtures.ControllerWindowIntegrationTests.tearDown
    frame = controller_fixtures.ControllerWindowIntegrationTests.frame
    button = controller_fixtures.ControllerWindowIntegrationTests.button
    publish = controller_fixtures.ControllerWindowIntegrationTests.publish
    menu = controller_fixtures.ControllerWindowIntegrationTests.menu

    def test_hidden_confirm_and_held_confirm_on_restore_cannot_answer(self):
        request = self.menu()
        self.window.handle_event(self.pg.event.Event(self.pg.WINDOWMINIMIZED))
        self.button("A")
        self.frame()
        self.window.handle_event(self.pg.event.Event(self.pg.WINDOWRESTORED))
        self.frame()
        self.assertIs(self.window.request, request)
        self.assertTrue(self.ui.responses.empty())
        self.button("A", False)
        self.frame()
        self.button("A")
        self.assertEqual(self.ui.responses.get_nowait(), (request.identifier, 1))


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for minimized windows")
class MinimizedLaunchTests(unittest.TestCase):
    def test_close_still_releases_the_actual_story_worker_in_the_idle_loop(self):
        ui = PixelUI(fast=True)
        rates, posted, forced = [], [], []

        class MinimizeThenCloseWindow(PixelWindow):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, **kwargs)
                native_clock = self.clock
                window = self

                class ClosingClock:
                    def tick(self, rate):
                        rates.append(rate)
                        if window.minimized:
                            window.pg.event.post(window.pg.event.Event(window.pg.QUIT))
                        return native_clock.tick(rate)

                self.clock = ClosingClock()

            def render(self):
                super().render()
                if self.request and self.request.label == "MAIN MENU" and not posted:
                    posted.append(True)
                    self.pg.event.post(self.pg.event.Event(self.pg.WINDOWMINIMIZED))

        def watchdog():
            if not ui.closed.wait(2):
                forced.append(True)
                ui.close()

        with tempfile.TemporaryDirectory() as directory:
            game = Game(ui, saves=SaveManager(Path(directory) / "saves"),
                        settings_manager=SettingsManager(Path(directory) / "settings.json"))
            guard = threading.Thread(target=watchdog)
            guard.start()
            try:
                with patch("roads_beneath_shadow.pixel_ui.PixelWindow", MinimizeThenCloseWindow):
                    launch_pixel_game(game, ui)
            finally:
                ui.close()
                guard.join(1)
        self.assertEqual(posted, [True])
        self.assertIn(15, rates)
        self.assertEqual(forced, [])
        self.assertFalse(any(worker.name == "roads-story" and worker.is_alive()
                             for worker in threading.enumerate()))
