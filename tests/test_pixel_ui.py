"""The graphical adapter must preserve engine input and release its worker."""

import importlib.util
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.pixel_ui import PixelUI, PixelWindow, UIEvent, launch_pixel_game, wrap_pixels
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.settings import SettingsManager
from roads_beneath_shadow.ui import InputClosed


class PixelQueueTests(unittest.TestCase):
    def test_close_releases_a_waiting_story_request(self):
        ui = PixelUI()
        result = []

        def wait():
            try:
                ui.choose("Menu", ["Continue"])
            except InputClosed:
                result.append("closed")

        worker = threading.Thread(target=wait)
        worker.start()
        event = ui.events.get(timeout=1)
        self.assertEqual(event.kind, "request")
        ui.close()
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())
        self.assertEqual(result, ["closed"])

    def test_hud_request_takes_a_snapshot_of_mutable_state(self):
        ui = PixelUI()
        state = GameState(Character.from_origin("Mira", ORIGINS[0]))
        ui.state_provider = lambda: state
        snapshot = ui._hud_snapshot()
        state.character.hp -= 3
        self.assertEqual(snapshot["hp"], state.character.hp + 3)
        self.assertEqual(snapshot["name"], "Mira")

    def test_graphical_text_does_not_include_ansi_sequences(self):
        ui = PixelUI()
        ui.write("\033[31mA warning\033[0m")
        self.assertEqual(ui.events.get_nowait().data["text"], "A warning")

    def test_empty_menu_is_rejected_before_waiting_for_input(self):
        ui = PixelUI()
        for method in (ui.choose, ui.choose_story):
            with self.assertRaises(ValueError):
                method("Menu", [])


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for graphical input tests")
class PixelSDLTests(unittest.TestCase):
    def setUp(self):
        self.ui = PixelUI(fast=True)
        self.window = PixelWindow(self.ui, size=(1000, 760))
        self.pg = self.window.pg
        self.workers = []
        self.results = []

    def tearDown(self):
        self.ui.close()
        for worker in self.workers:
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive(), "graphical worker remained blocked after close")
        self.pg.quit()

    def start(self, method):
        def run():
            try:
                self.results.append(method())
            except InputClosed:
                pass

        worker = threading.Thread(target=run)
        worker.start()
        self.workers.append(worker)
        self.await_request()

    def await_request(self):
        deadline = time.monotonic() + 2
        while self.window.request is None and time.monotonic() < deadline:
            self.window.drain()
            time.sleep(0.002)
        self.assertIsNotNone(self.window.request)
        self.window.render()

    def key(self, key, text=""):
        self.window.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=key, unicode=text, mod=0))

    def test_keyboard_selects_options_beyond_nine(self):
        self.start(lambda: self.ui.choose("Actions", [f"Action {index}" for index in range(1, 13)]))
        for _ in range(10):
            self.key(self.pg.K_DOWN)
        self.assertGreater(self.window.choice_scroll, 0)
        self.key(self.pg.K_RETURN)
        self.workers[-1].join(timeout=1)
        self.assertEqual(self.results, [11])

    def test_story_save_shortcut_is_distinct_from_menu_navigation(self):
        self.start(lambda: self.ui.choose_story("A fork", ["Follow the road", "Cross the marsh"]))
        self.key(self.pg.K_s, "s")
        self.workers[-1].join(timeout=1)
        self.assertEqual(self.results, ["s"])
        self.start(lambda: self.ui.choose("Menu", ["One", "Two"]))
        self.key(self.pg.K_s, "s")
        self.key(self.pg.K_SPACE, " ")
        self.workers[-1].join(timeout=1)
        self.assertEqual(self.results, ["s", 2])

    def test_unicode_name_entry_reaches_the_story_engine(self):
        self.start(lambda: self.ui.prompt("Traveler's name: "))
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Éowen"))
        self.key(self.pg.K_BACKSPACE)
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="n"))
        self.key(self.pg.K_RETURN)
        self.workers[-1].join(timeout=1)
        self.assertEqual(self.results, ["Éowen"])

    def test_wrapped_long_choice_is_clickable_without_losing_text(self):
        option = "Ask the watchman about the letter, the silver star, and the old roads beneath the ruined wayhouse."
        self.start(lambda: self.ui.choose("What do you do?", [option, "Leave"]))
        dimensions = self.window._choice_dimensions()
        self.assertGreater(len(dimensions[0][1]), 1)
        self.assertEqual(" ".join(dimensions[0][1]), option)
        rect, answer = self.window.choice_hits[0]
        self.assertEqual(answer, 1)
        self.window.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=rect.center))
        self.workers[-1].join(timeout=1)
        self.assertEqual(self.results, [1])

    def test_pixel_wrap_handles_long_words_at_any_width(self):
        source = "a" * 80
        lines = wrap_pixels(source, self.window.font, 90)
        self.assertEqual("".join(lines), source)
        self.assertTrue(all(self.window.font.size(line)[0] <= 90 for line in lines))

    def test_clear_and_pageup_preserve_all_narration(self):
        for index in range(40):
            self.ui.narrate(f"Remembered road {index}")
        self.ui.clear()
        self.ui.write("A new scene")
        self.window.drain()
        self.window.render()
        self.key(self.pg.K_PAGEUP)
        self.window.render()
        self.assertGreater(self.window.history_scroll, 0)
        self.assertEqual(self.window.history[0][0], "Remembered road 0")
        self.assertEqual(self.window.history[-1][0], "A new scene")

    def test_close_window_releases_input_wait(self):
        self.start(lambda: self.ui.choose("Menu", ["Continue"]))
        self.window.handle_event(self.pg.event.Event(self.pg.QUIT))
        self.workers[-1].join(timeout=1)
        self.assertTrue(self.ui.closed.is_set())
        self.assertFalse(self.workers[-1].is_alive())

    def test_worker_error_stays_visible_until_the_player_closes_it(self):
        self.ui.fast = False
        self.ui.narrate("The previous story page must not conceal an error.")
        self.start(lambda: self.ui.choose_story("Keep walking?", ["Continue"]))
        self.assertIsNotNone(self.window.narrative.current)
        self.ui.events.put(UIEvent("finished", {"error": "The journey stopped: a useful diagnostic"}))
        self.window.drain()
        visible = []
        draw = self.window._text

        def record(text, *args):
            visible.append(text)
            draw(text, *args)

        self.window._text = record
        self.window.render()
        self.assertFalse(self.ui.closed.is_set())
        self.assertEqual(self.window.error, "The journey stopped: a useful diagnostic")
        self.assertIn("THE JOURNEY STOPPED", visible)
        self.assertIn("a useful diagnostic", " ".join(visible))
        self.key(self.pg.K_RETURN)
        self.assertTrue(self.ui.closed.is_set())

    def test_new_journey_uses_native_requests_with_the_complete_engine(self):
        game = Game(self.ui)
        self.ui.state_provider = lambda: game.state
        self.start(game._new_journey)
        self.assertEqual(self.window.request.kind, "text")
        self.window.answer("Mira")
        self.await_request()
        self.assertEqual(self.window.request.label, "Choose your background")
        self.window.answer(2)
        self.await_request()
        self.assertEqual(self.window.request.label, "Accept this background?")
        self.window.answer(1)
        self.await_request()
        self.assertIn("Calenor", self.window.request.label)
        self.window.answer(2)
        self.workers[-1].join(timeout=1)
        self.assertEqual(self.results, [True])
        self.assertEqual(game.state.character.name, "Mira")
        self.assertEqual(game.state.character.origin, ORIGINS[1].origin_id)
        self.assertTrue(game.state.flags["lesson_tracking"])

    def test_screenshot_renders_and_closes_the_actual_game_worker(self):
        self.pg.quit()
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "title.png"
            ui = PixelUI(fast=True)
            launch_pixel_game(Game(ui), ui, screenshot=target)
            self.assertTrue(target.is_file())
            picture = self.pg.image.load(str(target))
            self.assertEqual(picture.get_size(), (1200, 900))
            self.assertTrue(ui.closed.is_set())


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for graphical launch tests")
class PixelLaunchTests(unittest.TestCase):
    def test_actual_main_menu_quit_exits_without_a_second_acknowledgement(self):
        ui = PixelUI(fast=True)
        posted = []
        forced = []

        class QuitWindow(PixelWindow):
            def render(self):
                super().render()
                if self.request and self.request.label == "MAIN MENU" and not posted:
                    posted.append(self.request.options[-1])
                    for _ in self.request.options[:-1]:
                        self.pg.event.post(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_DOWN, unicode="", mod=0))
                    self.pg.event.post(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_RETURN, unicode="", mod=0))

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
                with patch("roads_beneath_shadow.pixel_ui.PixelWindow", QuitWindow):
                    launch_pixel_game(game, ui)
            finally:
                ui.close()
                guard.join(1)
        self.assertEqual(posted, ["Quit"])
        self.assertEqual(forced, [], "Quit waited for another acknowledgement")
        self.assertTrue(ui.closed.is_set())


if __name__ == "__main__":
    unittest.main()
