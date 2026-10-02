"""Real input coverage for pausing and returning to an unchanged story decision."""

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

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.pixel_ui import PixelUI, PixelWindow
from roads_beneath_shadow.pixel_world import WORLD_MAPS
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.settings import SettingsManager
from roads_beneath_shadow.ui import InputClosed


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for desktop controls")
class JourneyControlsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ui = PixelUI(text_speed="instant")
        self.window = PixelWindow(self.ui, size=(1000, 760))
        self.pg = self.window.pg
        self.game = Game(self.ui, saves=SaveManager(Path(self.temp.name) / "saves"), settings_manager=SettingsManager(Path(self.temp.name) / "settings.json"))
        self.game.state = GameState(Character.from_origin("Mira", ORIGINS[0]), scene="bree_exploration")
        self.ui.state_provider = lambda: self.game.state
        self.results = []
        self.errors = []
        self.worker = None

    def tearDown(self):
        self.ui.close()
        if self.worker:
            self.worker.join(1)
            self.assertFalse(self.worker.is_alive())
        self.pg.quit()
        self.temp.cleanup()
        self.assertEqual(self.errors, [])

    def start(self):
        def run():
            try:
                self.results.append(self.game._story_choice("WHERE WILL YOU INVESTIGATE?", tuple(point.option for point in WORLD_MAPS["bree"].points)))
            except InputClosed:
                pass
            except Exception as error:
                self.errors.append(error)
        self.worker = threading.Thread(target=run)
        self.worker.start()
        self.await_request(lambda request: request.story)

    def await_request(self, predicate):
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            self.window.drain()
            self.window.render()
            if self.window.request and predicate(self.window.request):
                return self.window.request
            time.sleep(0.002)
        self.fail("The expected desktop request did not arrive")

    def key(self, key, text=""):
        self.window.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=key, unicode=text, mod=0))

    def test_pause_settings_and_resume_preserve_world_and_every_story_page(self):
        self.ui.narrate(" ".join(f"memory{index}" for index in range(220)))
        self.start()
        while self.window.reading:
            self.key(self.pg.K_RETURN)
            self.window.render()
        old_pages = self.window.narrative.pages
        old_index = self.window.narrative.index
        old_position = self.window.world.player_position
        before = self.game.state.to_dict()
        self.key(self.pg.K_ESCAPE)
        self.await_request(lambda request: request.label == "JOURNEY PAUSED")
        self.key(self.pg.K_3, "3")
        self.await_request(lambda request: request.label == "SETTINGS")
        self.key(self.pg.K_4, "4")
        self.await_request(lambda request: request.label == "SETTINGS")
        self.assertTrue(self.ui.reduced_motion)
        self.key(self.pg.K_ESCAPE)
        self.await_request(lambda request: request.label == "JOURNEY PAUSED")
        self.key(self.pg.K_ESCAPE)
        self.await_request(lambda request: request.story)
        self.assertEqual(self.game.state.to_dict(), before)
        self.assertEqual(self.window.world.player_position, old_position)
        self.assertEqual(self.window.narrative.pages, old_pages)
        self.assertEqual(self.window.narrative.index, old_index)
        self.assertFalse(self.window.reading)
        self.assertTrue(self.game.settings_manager.load().reduced_motion)
        self.key(self.pg.K_BACKSPACE)
        self.assertEqual(self.window.narrative.index, old_index - 1)
        self.assertEqual(self.results, [])

    def test_pause_can_return_to_menu_without_advancing_a_story_option(self):
        self.start()
        before = self.game.state.to_dict()
        self.key(self.pg.K_ESCAPE)
        self.await_request(lambda request: request.label == "JOURNEY PAUSED")
        self.key(self.pg.K_5, "5")
        self.worker.join(1)
        self.assertEqual(self.results, [None])
        self.assertEqual(self.game.state.to_dict(), before)

    def test_inventory_return_preserves_keyboard_selection_and_confirmation(self):
        self.start()
        self.key(self.pg.K_DOWN)
        self.assertEqual(self.window.selected, 1)
        before = self.game.state.to_dict()
        self.key(self.pg.K_i, "i")
        self.await_request(lambda request: request.kind == "panel")
        self.key(self.pg.K_ESCAPE)
        self.await_request(lambda request: request.story)
        self.assertEqual(self.window.selected, 1)
        self.assertTrue(self.window._menu_focused)
        self.assertEqual(self.game.state.to_dict(), before)
        self.key(self.pg.K_RETURN)
        self.worker.join(1)
        self.assertEqual(self.results, [2])

    def test_larger_text_after_pause_keeps_completed_story_and_exploration_ready(self):
        self.window.handle_event(self.pg.event.Event(self.pg.VIDEORESIZE, w=760, h=560))
        self.ui.title("BREE BEFORE MIDNIGHT")
        self.ui.narrate("The rain weakens to a cold mist. Bree has drawn in upon itself: shutters closed, hedges whispering, the watch calling from one locked gate to another. Somewhere beyond those gates a horn answers at long intervals. Whoever commanded the Orcs has not given up the hunt.")
        self.start()
        while self.window.reading:
            self.key(self.pg.K_RETURN)
            self.window.render()
        position = self.window.world.player_position
        before = self.game.state.to_dict()
        old_total = len(self.window.narrative.pages)
        self.key(self.pg.K_ESCAPE)
        self.await_request(lambda request: request.label == "JOURNEY PAUSED")
        self.key(self.pg.K_3, "3")
        self.await_request(lambda request: request.label == "SETTINGS")
        for _ in range(2):
            self.window.selected = 9
            self.key(self.pg.K_RETURN)
            self.await_request(lambda request: request.label == "SETTINGS")
        self.key(self.pg.K_ESCAPE)
        self.await_request(lambda request: request.label == "JOURNEY PAUSED")
        self.key(self.pg.K_ESCAPE)
        self.await_request(lambda request: request.story)
        self.assertEqual(self.ui.text_size, "larger")
        self.assertGreater(len(self.window.narrative.pages), old_total)
        self.assertEqual(self.window.narrative.index, len(self.window.narrative.pages) - 1)
        self.assertFalse(self.window.reading)
        self.assertTrue(self.window.world.active)
        self.assertEqual(self.window.world.player_position, position)
        self.assertEqual(self.game.state.to_dict(), before)
        self.key(self.pg.K_BACKSPACE)
        self.assertTrue(self.window._page_finished)

    def test_f1_controls_close_back_to_the_exact_live_options(self):
        self.start()
        options = self.window.request.options
        before = self.game.state.to_dict()
        original_request = self.window.request
        self.key(self.pg.K_F1)
        self.window.render()
        self.assertTrue(self.window.panels.active)
        self.assertIs(self.window.request, original_request)
        self.key(self.pg.K_ESCAPE)
        self.await_request(lambda request: request.story)
        self.assertEqual(self.window.request.options, options)
        self.assertEqual(self.game.state.to_dict(), before)

    def test_controls_during_reading_preserve_the_exact_page_and_reveal(self):
        self.ui.set_text_speed("normal")
        self.ui.narrate(" ".join(f"memory{index}" for index in range(100)))
        self.start()
        page = self.window.narrative.current
        self.assertTrue(self.window.reading)
        self.key(self.pg.K_F1)
        reveal = self.window._page_reveal
        self.window.render()
        self.assertEqual(self.window._page_reveal, reveal)
        self.key(self.pg.K_ESCAPE)
        self.assertIs(self.window.narrative.current, page)
        self.assertEqual(self.window._page_reveal, reveal)
        self.assertTrue(self.window.reading)
        self.assertEqual(self.results, [])

    def test_focus_loss_stops_keyboard_and_click_movement(self):
        self.start()
        self.key(self.pg.K_d, "d")
        self.window.world.update(0.05)
        self.window.world.walk_to(WORLD_MAPS["bree"].spawn)
        self.window.handle_event(self.pg.event.Event(self.pg.WINDOWFOCUSLOST))
        position = self.window.world.player_position
        self.window.world.update(0.2)
        self.assertEqual(self.window.world.player_position, position)
        self.assertEqual(self.results, [])

    def test_resize_keeps_revealed_source_text_visible(self):
        self.ui.set_text_speed("normal")
        self.ui.narrate(" ".join(f"memory{index}" for index in range(100)))
        self.start()
        self.window._page_reveal = 70
        before = " ".join(self.window.narrative.current.text[:70].split())
        request = self.window.request
        self.window.handle_event(self.pg.event.Event(self.pg.VIDEORESIZE, w=760, h=560))
        self.window.render()
        after = " ".join(self.window.narrative.current.text[:int(self.window._page_reveal)].split())
        self.assertTrue(after.startswith(before))
        self.assertIs(self.window.request, request)
        self.assertEqual(self.results, [])

    def test_menu_arrows_and_enter_confirm_the_selected_exploration_option(self):
        self.start()
        self.key(self.pg.K_DOWN)
        self.assertEqual(self.window.selected, 1)
        self.key(self.pg.K_RETURN)
        self.worker.join(1)
        self.assertEqual(self.results, [2])

    def test_resizing_completed_story_keeps_exploration_and_previous_pages_read(self):
        self.ui.set_text_speed("normal")
        self.ui.narrate(" ".join(f"memory{index}" for index in range(170)))
        self.start()
        while self.window.reading:
            self.key(self.pg.K_RETURN)
            self.window.render()
        request = self.window.request
        position = self.window.world.player_position
        self.window.handle_event(self.pg.event.Event(self.pg.VIDEORESIZE, w=760, h=560))
        self.window.render()
        self.assertFalse(self.window.reading)
        self.assertTrue(self.window.world.active)
        self.assertIs(self.window.request, request)
        self.assertEqual(self.window.world.player_position, position)
        self.key(self.pg.K_BACKSPACE)
        self.assertTrue(self.window._page_finished)
        self.assertEqual(self.results, [])

    def test_load_an_earlier_decision_in_the_same_scene_does_not_restore_later_prose(self):
        options = tuple(point.option for point in WORLD_MAPS["bree"].points)
        self.game.saves.save(1, self.game.state)
        self.game.state.flags["later_progress"] = True

        def run():
            try:
                self.ui.title("BREE")
                self.ui.narrate("LATE source from a later investigation.")
                self.game._story_choice("WHERE WILL YOU INVESTIGATE?", options)
                self.ui.choose("MAIN MENU", ["Load an earlier save"])
                self.game.state = self.game.saves.load(1)
                self.ui.clear()
                self.ui.title("BREE")
                self.ui.narrate("EARLY source from the loaded investigation.")
                self.game._story_choice("WHERE WILL YOU INVESTIGATE?", options)
            except InputClosed:
                pass
            except Exception as error:
                self.errors.append(error)

        self.worker = threading.Thread(target=run)
        self.worker.start()
        first = self.await_request(lambda request: request.story)
        self.key(self.pg.K_m, "m")
        self.await_request(lambda request: request.label == "MAIN MENU")
        self.key(self.pg.K_1, "1")
        current = self.await_request(lambda request: request.story and request.identifier != first.identifier)
        self.assertEqual(current.options, first.options)
        self.assertNotEqual(current.context["decision_id"], first.context["decision_id"])
        self.assertFalse(self.game.state.flags.get("later_progress", False))
        self.assertIn("EARLY source", " ".join(beat.text for beat in self.window.narrative.beats))
        self.assertNotIn("LATE source", " ".join(beat.text for beat in self.window.narrative.beats))
