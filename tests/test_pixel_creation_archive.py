"""Creation previews must not become another traveler's recorded journey."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.pixel_ui import PixelUI, PixelWindow
from roads_beneath_shadow.profile import ProfileManager
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.settings import SettingsManager, UserSettings
from roads_beneath_shadow.ui import InputClosed


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for creation archive controls")
class CreationArchiveTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        saves = SaveManager(root / "saves")
        saves.save(1, GameState(Character.from_origin("Arin", ORIGINS[0]), scene="bree_exploration"))
        self.ui = PixelUI(fast=False, text_speed="instant", sound=False)
        self.game = Game(
            self.ui, saves=saves, profile=ProfileManager(root / "profile.json"),
            settings_manager=SettingsManager(root / "settings.json"),
            user_settings=UserSettings(text_speed="instant", sound=False),
        )
        self.ui.state_provider = lambda: self.game.state
        self.window = PixelWindow(self.ui, size=(760, 560))
        self.pg = self.window.pg
        self.errors = []

        def run():
            try:
                self.game.run()
            except InputClosed:
                pass
            except BaseException as error:
                self.errors.append(error)

        self.worker = threading.Thread(target=run, daemon=True)
        self.worker.start()
        self.wait_for(lambda request: request.label == "MAIN MENU")
        self.choose("Load a journey")
        self.wait_for(lambda request: request.kind == "panel" and request.context["kind"] == "saves")
        self.key(self.pg.K_RETURN)
        request = self.wait_for(lambda request: request.story)
        self.previous_state = self.game.state
        self.previous_snapshot = self.game.state.to_dict()
        self.previous_decision = request.label, request.options
        self.previous_position = self.window.world.player_position
        self.search("Arin")
        self.assertTrue(self.window.archive.matches)
        self.close_archive()

    def tearDown(self):
        self.ui.close()
        self.worker.join(2)
        self.pg.quit()
        self.temporary.cleanup()
        self.assertFalse(self.worker.is_alive(), "Game.run did not release its pending request")
        self.assertEqual(self.errors, [])

    def key(self, key, *, text="", mod=0):
        self.window.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=key, unicode=text, mod=mod))

    def wait_for(self, predicate):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.window.drain()
            self.window.render()
            request = self.window.request
            if self.window.reading:
                self.key(self.pg.K_RETURN)
            elif request is not None and predicate(request):
                return request
            self.assertEqual(self.errors, [])
            time.sleep(0.001)
        self.fail(f"Game.run did not reach the expected request; current={self.window.request!r}")

    def choose(self, fragment):
        request = self.window.request
        self.window.selected = next(index for index, option in enumerate(request.options) if fragment in option)
        self.window._keep_selection_visible()
        self.window.render()
        self.key(self.pg.K_RETURN)

    def search(self, query):
        self.key(self.pg.K_TAB)
        self.window.render()
        self.key(self.pg.K_f, mod=self.pg.KMOD_CTRL)
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text=query))
        self.window.render()

    def close_archive(self):
        self.key(self.pg.K_ESCAPE)
        self.key(self.pg.K_TAB)
        self.assertFalse(self.window.transcript_open)

    def begin_creation(self):
        self.key(self.pg.K_m, text="m")
        self.wait_for(lambda request: request.label == "MAIN MENU")
        self.previous_history = tuple(self.window.history)
        self.choose("Begin a new journey")
        self.wait_for(lambda request: request.label.startswith("Discard Arin"))
        self.choose("Discard it")
        self.wait_for(lambda request: request.kind == "text")

    def preview_healer(self):
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Míra"))
        self.key(self.pg.K_RETURN)
        self.wait_for(lambda request: request.kind == "panel" and request.context["kind"] == "background")
        self.key(self.pg.K_RIGHT)
        self.key(self.pg.K_RIGHT)
        self.window.render()
        self.key(self.pg.K_RETURN)
        self.wait_for(lambda request: request.label == "Accept this background?")
        self.assertIn(ORIGINS[2].description, [text for text, _, _ in self.window.history])

    def assert_canceled_creation_returns_to_the_recorded_wayfarer(self):
        self.wait_for(lambda request: request.label == "MAIN MENU")
        self.assertIs(self.game.state, self.previous_state)
        self.assertEqual(self.game.state.to_dict(), self.previous_snapshot)
        self.assertEqual(tuple(self.window.history[:len(self.previous_history)]), self.previous_history)
        self.assertEqual(self.window.archive.query, "Arin")
        self.assertNotIn("WHO WALKS THE ROAD?", [text for text, _, _ in self.window.history])
        self.choose("Continue Arin")
        request = self.wait_for(lambda request: request.story)
        self.assertEqual((request.label, request.options), self.previous_decision)
        self.assertEqual(self.window.world.player_position, self.previous_position)
        self.assertEqual(self.game.state.character.origin, "bree_wayfarer")
        self.search("Field Remedy")
        self.assertEqual(self.window.archive.matches, [])
        self.assertNotIn(ORIGINS[2].description, [text for text, _, _ in self.window.archive.entries])
        self.close_archive()
        self.assertIs(self.window.request, request)
        self.assertEqual(self.game.state.to_dict(), self.previous_snapshot)

    def test_canceled_named_healer_preview_does_not_enter_the_wayfarer_archive(self):
        self.begin_creation()
        self.preview_healer()
        self.choose("Choose again")
        self.wait_for(lambda request: request.kind == "panel" and request.context["kind"] == "background")
        self.key(self.pg.K_ESCAPE)
        self.assert_canceled_creation_returns_to_the_recorded_wayfarer()

    def test_canceled_name_entry_discards_generic_creation_prose(self):
        self.begin_creation()
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Míra"))
        self.key(self.pg.K_ESCAPE)
        self.assert_canceled_creation_returns_to_the_recorded_wayfarer()

    def test_accepted_new_traveler_starts_a_clean_archive_without_the_prior_query(self):
        self.begin_creation()
        self.preview_healer()
        self.choose("Yes")
        self.wait_for(lambda request: request.label == "What lesson from Calenor do you carry?")
        self.assertIsNot(self.game.state, self.previous_state)
        self.assertEqual(self.game.state.character.name, "Míra")
        self.assertEqual(self.game.state.character.origin, "healers_apprentice")
        self.assertEqual(self.window.archive.query, "")
        self.assertNotIn("Welcome back, Arin.", [text for text, _, _ in self.window.history])
        self.search("Arin")
        self.assertEqual(self.window.archive.matches, [])
        self.close_archive()


if __name__ == "__main__":
    unittest.main()
