"""Real desktop utility returns keep read prose and refresh earned choices."""

from __future__ import annotations

import importlib.util
import os
import random
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

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


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for live story choices")
class LiveStoryChoicesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.ui = PixelUI(text_speed="instant", sound=False)
        self.window = PixelWindow(self.ui, size=(1000, 760))
        self.pg = self.window.pg
        self.game = Game(
            self.ui,
            saves=SaveManager(root / "saves"),
            profile=ProfileManager(root / "profile.json"),
            settings_manager=SettingsManager(root / "settings.json"),
            user_settings=UserSettings(text_speed="instant", sound=False),
            rng=random.Random(812),
        )
        self.ui.state_provider = lambda: self.game.state
        self.worker = None
        self.results = []
        self.errors = []

    def tearDown(self):
        self.ui.close()
        if self.worker is not None:
            self.worker.join(2)
            self.assertFalse(self.worker.is_alive(), "The story worker was not released")
        self.pg.quit()
        self.temporary.cleanup()
        self.assertEqual(self.errors, [])

    def start(self, operation):
        def run():
            try:
                self.results.append(operation())
            except InputClosed:
                pass
            except Exception as error:
                self.errors.append(error)

        self.worker = threading.Thread(target=run)
        self.worker.start()

    def await_request(self, predicate, *, previous=None):
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline:
            self.window.drain()
            self.window.render()
            request = self.window.request
            if request is not None and request is not previous and predicate(request):
                return request
            if self.errors:
                self.fail(f"The story worker failed: {self.errors!r}")
            time.sleep(0.002)
        self.fail("The expected story or utility request did not arrive")

    def key(self, key, text=""):
        self.window.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=key, unicode=text, mod=0))

    def finish_reading(self):
        for _ in range(40):
            if not self.window.reading:
                return
            self.key(self.pg.K_RETURN)
            self.window.render()
        self.fail("The story did not finish within forty pages")

    def start_lantern(self, *, hp, focus=None):
        state = GameState(
            Character.from_origin("Mira", ORIGINS[0]),
            chapter=2,
            scene="part2_vigil",
            visited=["part2_vigil"],
        )
        state.character.hp = hp
        if focus is not None:
            state.character.focus = focus
        self.game.state = state
        self.start(lambda: self.game.part_two.run_scene(state))
        request = self.await_request(lambda request: request.story)
        self.finish_reading()
        self.assertTrue(self.window.world.active)
        return request

    def assert_reading_restored(self, director, pages, position):
        self.assertIs(self.window.narrative, director)
        self.assertEqual(self.window.narrative.pages, pages)
        self.assertEqual(self.window.narrative.index, len(pages) - 1)
        self.assertFalse(self.window.reading)
        self.assertTrue(self.window.world.active)
        self.assertEqual(self.window.world.player_position, position)

    def visible_text(self):
        drawn = []
        original = self.window._text

        def record(text, *args):
            drawn.append(text)
            return original(text, *args)

        self.window._text = record
        try:
            self.window.render()
        finally:
            self.window._text = original
        return " ".join(drawn)

    def test_manual_save_success_is_drawn_after_returning_to_the_unchanged_story(self):
        self.start_lantern(hp=26)
        director, pages = self.window.narrative, self.window.narrative.pages
        position = self.window.world.player_position
        before, rng = self.game.state.to_dict(), self.game.rng.getstate()

        self.key(self.pg.K_F5)
        request = self.await_request(lambda request: request.kind == "panel")
        self.assertEqual(request.context["data"]["mode"], "save")
        self.key(self.pg.K_RETURN)
        self.await_request(lambda request: request.story)

        self.assertIn("Journey saved in slot 1.", self.visible_text())
        self.assertTrue(any(text == "Journey saved in slot 1." for text, _, _ in self.window.history))
        self.assertEqual(self.game.saves.load(1).to_dict(), before)
        self.assert_reading_restored(director, pages, position)
        self.assertEqual(self.game.state.to_dict(), before)
        self.assertEqual(self.game.rng.getstate(), rng)

    def test_manual_save_failure_is_drawn_without_losing_the_current_story(self):
        self.start_lantern(hp=26)
        director, pages = self.window.narrative, self.window.narrative.pages
        position = self.window.world.player_position
        before, rng = self.game.state.to_dict(), self.game.rng.getstate()

        self.key(self.pg.K_F5)
        self.await_request(lambda request: request.kind == "panel")
        with patch.object(self.game.saves, "save", side_effect=OSError("The storage volume is full")):
            self.key(self.pg.K_RETURN)
            self.await_request(lambda request: request.story)

        notice = "Could not save the journey: The storage volume is full"
        self.assertIn(notice, self.visible_text())
        self.assertTrue(any(text == notice for text, _, _ in self.window.history))
        self.assertFalse(self.game.saves._path(1).exists())
        self.assert_reading_restored(director, pages, position)
        self.assertEqual(self.game.state.to_dict(), before)
        self.assertEqual(self.game.rng.getstate(), rng)

    def test_enabling_autosave_surfaces_a_checkpoint_failure_on_return_to_the_story(self):
        self.game.user_settings.autosave = False
        self.start_lantern(hp=26)
        director, pages = self.window.narrative, self.window.narrative.pages
        position = self.window.world.player_position
        before, rng = self.game.state.to_dict(), self.game.rng.getstate()

        self.key(self.pg.K_p, "p")
        self.await_request(lambda request: request.label == "JOURNEY PAUSED")
        self.key(self.pg.K_3, "3")
        settings = self.await_request(lambda request: request.label == "SETTINGS")
        self.key(self.pg.K_9, "9")
        self.await_request(lambda request: request.label == "SETTINGS", previous=settings)
        self.assertTrue(self.game.user_settings.autosave)
        self.key(self.pg.K_ESCAPE)
        self.await_request(lambda request: request.label == "JOURNEY PAUSED")
        with patch.object(self.game.checkpoints, "record", side_effect=OSError("The checkpoint volume is full")):
            self.key(self.pg.K_ESCAPE)
            self.await_request(lambda request: request.story)

        notice = "Checkpoint could not be saved: The checkpoint volume is full"
        self.assertIn(notice, self.visible_text())
        self.assertTrue(any(text == notice for text, _, _ in self.window.history))
        self.assertFalse(self.game.checkpoints.path.exists())
        self.assert_reading_restored(director, pages, position)
        self.assertEqual(self.game.state.to_dict(), before)
        self.assertEqual(self.game.rng.getstate(), rng)

    def test_main_menu_continue_keeps_completed_reading_on_the_same_journey(self):
        self.game.state = GameState(
            Character.from_origin("Mira", ORIGINS[0]),
            scene="bree_exploration",
            visited=["bree_exploration"],
        )
        self.start(self.game.run)
        self.await_request(lambda request: request.label == "MAIN MENU")
        self.key(self.pg.K_RETURN)
        original = self.await_request(lambda request: request.story)
        self.finish_reading()
        director, pages = self.window.narrative, self.window.narrative.pages
        position = self.window.world.player_position
        before, rng = self.game.state.to_dict(), self.game.rng.getstate()

        self.key(self.pg.K_m, "m")
        self.await_request(lambda request: request.label == "MAIN MENU")
        self.assertEqual(self.game.state.to_dict(), before)
        self.key(self.pg.K_RETURN)
        resumed = self.await_request(lambda request: request.story)

        self.assertEqual(resumed.options, original.options)
        self.assertNotEqual(resumed.context["decision_id"], original.context["decision_id"])
        self.assert_reading_restored(director, pages, position)
        self.assertEqual(self.game.state.to_dict(), before)
        self.assertEqual(self.game.rng.getstate(), rng)
        self.assertEqual(self.results, [])

    def test_main_menu_ignores_the_azerty_superscript_key_then_accepts_an_arabic_digit(self):
        self.start(self.game.run)
        original = self.await_request(lambda request: request.label == "MAIN MENU")
        rng = self.game.rng.getstate()

        self.key(self.pg.K_BACKQUOTE, "²")
        self.window.render()
        self.assertIs(self.window.request, original)
        self.assertIsNone(self.game.state)
        self.assertEqual(self.game.rng.getstate(), rng)

        self.key(self.pg.K_2, "٢")
        loaded = self.await_request(lambda request: request.kind == "panel")
        self.assertEqual(loaded.context["kind"], "saves")
        self.assertEqual(loaded.context["data"]["mode"], "load")
        self.assertIsNone(self.game.state)
        self.assertEqual(self.game.rng.getstate(), rng)

    def test_lantern_settings_refresh_the_cap_without_replaying_prose_or_resting(self):
        self.game.user_settings.difficulty = "shadow"
        self.game.combat.set_difficulty("hard")
        original = self.start_lantern(hp=1, focus=0)
        director, pages = self.window.narrative, self.window.narrative.pages
        position = self.window.world.player_position
        before, rng = self.game.state.to_dict(), self.game.rng.getstate()
        self.assertIn("up to 9 Health", " ".join(original.options))

        self.key(self.pg.K_p, "p")
        self.await_request(lambda request: request.label == "JOURNEY PAUSED")
        self.key(self.pg.K_3, "3")
        settings = self.await_request(lambda request: request.label == "SETTINGS")
        self.key(self.pg.K_6, "6")
        self.await_request(lambda request: request.label == "SETTINGS", previous=settings)
        self.assertEqual(self.game.user_settings.difficulty, "story")
        self.key(self.pg.K_ESCAPE)
        self.await_request(lambda request: request.label == "JOURNEY PAUSED")
        self.key(self.pg.K_ESCAPE)
        refreshed = self.await_request(lambda request: request.story)

        self.assertIn("up to 28 Health", " ".join(refreshed.options))
        self.assertEqual(refreshed.context["decision_id"], original.context["decision_id"])
        self.assertNotEqual(refreshed.options, original.options)
        self.assertEqual(tuple(self.game._active_decision["options"]), refreshed.options)
        rest = next(point for point in self.window.world.points if point.option.startswith("Rest and tend"))
        self.assertIn("up to 28 Health", rest.option)
        self.assert_reading_restored(director, pages, position)
        self.assertEqual(self.game.state.to_dict(), before)
        self.assertEqual(self.game.rng.getstate(), rng)

    def test_lantern_inventory_healing_removes_rest_and_keeps_the_shifted_exit_correct(self):
        original = self.start_lantern(hp=26)
        director, pages = self.window.narrative, self.window.narrative.pages
        position = self.window.world.player_position
        before, rng = self.game.state.to_dict(), self.game.rng.getstate()
        self.assertEqual(len(original.options), 3)
        self.assertTrue(original.options[1].startswith("Rest and tend"))

        self.key(self.pg.K_i, "i")
        inventory = self.await_request(lambda request: request.kind == "panel")
        self.assertEqual(inventory.context["kind"], "inventory")
        self.key(self.pg.K_TAB)
        self.key(self.pg.K_TAB)
        self.assertEqual(self.window.panels.tab, "supplies")
        self.assertEqual(self.window.panels.visible_items()[0]["id"], "healing_herb")
        self.key(self.pg.K_RETURN)
        self.await_request(lambda request: request.kind == "panel", previous=inventory)
        self.assertEqual(self.game.state.character.hp, self.game.state.character.max_hp)
        self.assertNotIn("healing_herb", self.game.state.character.inventory)
        self.key(self.pg.K_ESCAPE)
        refreshed = self.await_request(lambda request: request.story)

        self.assertEqual(refreshed.options, ("Sit beside Calenor for a moment", "Enter the Last Seal"))
        self.assertEqual(refreshed.context["decision_id"], original.context["decision_id"])
        self.assertFalse(any(point.option.startswith("Rest and tend") for point in self.window.world.points))
        self.assert_reading_restored(director, pages, position)
        expected = before
        expected["character"]["hp"] = self.game.state.character.max_hp
        expected["character"]["inventory"].pop("healing_herb")
        self.assertEqual(self.game.state.to_dict(), expected)
        self.assertEqual(self.game.rng.getstate(), rng)

        self.key(self.pg.K_DOWN)
        self.key(self.pg.K_RETURN)
        self.worker.join(2)
        self.assertEqual(self.results, [True])
        expected["scene"] = "part2_last_seal"
        self.assertEqual(self.game.state.to_dict(), expected)
        self.assertEqual(self.game.rng.getstate(), rng)


if __name__ == "__main__":
    unittest.main()
