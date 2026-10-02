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

    def start_name_prompt(self):
        def run():
            try:
                self.results.append(self.ui.prompt("Traveler's name: "))
            except InputClosed:
                pass
            except Exception as error:
                self.errors.append(error)
        self.worker = threading.Thread(target=run)
        self.worker.start()
        return self.await_request(lambda request: request.kind == "text")

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

    def test_hovering_the_already_selected_menu_option_takes_focus_from_a_look(self):
        self.start()
        look = next(look for look in WORLD_MAPS["bree"].looks if look.key == "pony_sign")
        rect = self.window.world._rect
        position = (rect.left + round(look.position[0] * rect.width / 320), rect.top + round(look.position[1] * rect.height / 240))
        self.window.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=position))
        for _ in range(150):
            self.window.world.update(0.05)
        self.key(self.pg.K_e, "e")
        self.assertTrue(self.window.world.inspection_open)
        self.key(self.pg.K_e, "e")
        self.window.render()
        self.assertEqual(self.window.selected, 0)
        self.assertFalse(self.window._menu_focused)
        self.window.handle_event(self.pg.event.Event(self.pg.MOUSEMOTION,
            pos=self.window.choice_hits[0][0].center, rel=(0, 0), buttons=(0, 0, 0)))
        self.key(self.pg.K_RETURN)
        self.worker.join(1)
        self.assertEqual(self.results, [1])
        self.assertFalse(self.window.world.inspection_open)

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
        self.key(self.pg.K_TAB)
        self.window.render()
        self.assertTrue(any("EARLY source" in text for text, _, _ in self.window.archive.entries))
        self.assertFalse(any("LATE source" in text for text, _, _ in self.window.archive.entries))

    def test_name_composition_return_waits_for_committed_text(self):
        request = self.start_name_prompt()
        self.assertIsNone(self.window.hud)
        self.assertEqual(self.game.state.character.name, "Mira")
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Old name"))
        self.window.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_a, mod=self.pg.KMOD_CTRL, unicode=""))
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTEDITING, text="Éowen", start=0, length=5))
        self.window.render()
        self.key(self.pg.K_RETURN)
        self.key(self.pg.K_BACKSPACE)
        self.assertIs(self.window.request, request)
        self.assertEqual(self.window.entry, "Old name")
        self.assertTrue(self.ui.responses.empty())
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Éowen"))
        self.key(self.pg.K_RETURN)
        self.worker.join(1)
        self.assertEqual(self.results, ["Éowen"])

    def test_name_editing_inserts_at_home_and_replaces_a_selected_suffix(self):
        self.start_name_prompt()
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Silver Star"))
        self.key(self.pg.K_HOME)
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Mira "))
        self.key(self.pg.K_END)
        for _ in range(4):
            self.window.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_LEFT, mod=self.pg.KMOD_SHIFT, unicode=""))
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Road"))
        self.key(self.pg.K_HOME)
        self.key(self.pg.K_DELETE)
        self.assertEqual(self.window.entry, "ira Silver Road")
        self.key(self.pg.K_RETURN)
        self.worker.join(1)
        self.assertEqual(self.results, ["ira Silver Road"])

    def test_native_composition_navigation_does_not_move_the_committed_name_caret(self):
        self.start_name_prompt()
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Mira "))
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTEDITING, text="Éowen", start=0, length=5))
        self.key(self.pg.K_HOME)
        self.key(self.pg.K_LEFT)
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Éowen"))
        self.assertEqual(self.window.entry, "Mira Éowen")
        self.key(self.pg.K_RETURN)
        self.worker.join(1)
        self.assertEqual(self.results, ["Mira Éowen"])

    def test_clicking_begin_after_text_input_in_the_same_frame_uses_current_name(self):
        self.start_name_prompt()
        button = self.window.choice_hits[0][0]
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Éowen"))
        self.window.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=button.center))
        self.worker.join(1)
        self.assertEqual(self.results, ["Éowen"])

    def test_canceling_name_entry_restores_previous_traveler_on_the_main_menu(self):
        previous = self.game.state
        before = previous.to_dict()
        self.ui.narrate("Mira's earlier discovery stays in her archive.")
        self.window.drain()

        def run():
            try:
                self.results.append(self.game._new_journey())
                self.ui.choose("MAIN MENU", ["Continue the current journey"])
            except InputClosed:
                pass
            except Exception as error:
                self.errors.append(error)

        self.worker = threading.Thread(target=run)
        self.worker.start()
        self.await_request(lambda request: request.label.startswith("Discard"))
        self.key(self.pg.K_2, "2")
        request = self.await_request(lambda request: request.kind == "text")
        while self.window.reading:
            self.key(self.pg.K_RETURN)
            self.window.render()
        self.assertTrue(request.allow_back)
        self.assertIsNone(self.window.hud)
        self.window.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=self.window.utility_hits[0][0].center))
        self.await_request(lambda request: request.label == "MAIN MENU")
        self.assertEqual(self.results, [False])
        self.assertIs(self.game.state, previous)
        self.assertEqual(self.game.state.to_dict(), before)
        self.assertEqual(self.window.hud["name"], "Mira")
        self.assertTrue(any("earlier discovery" in text for text, _, _ in self.window.history))

    def test_confirmed_new_traveler_has_their_own_hud_for_lesson_and_opening(self):
        previous = self.game.state
        self.ui.narrate("Mira's private earlier discovery.")
        self.window.drain()
        self.window.archive.query = "private"

        def run():
            try:
                self.results.append(self.game._new_journey())
                self.ui.narrate("Aerin's own road begins here.")
                self.ui.pause("The opening begins")
            except InputClosed:
                pass
            except Exception as error:
                self.errors.append(error)

        self.worker = threading.Thread(target=run)
        self.worker.start()
        self.await_request(lambda request: request.label.startswith("Discard"))
        self.key(self.pg.K_2, "2")
        self.await_request(lambda request: request.kind == "text")
        while self.window.reading:
            self.key(self.pg.K_RETURN)
            self.window.render()
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Aerin"))
        self.key(self.pg.K_RETURN)
        self.await_request(lambda request: request.kind == "panel")
        self.key(self.pg.K_1, "1")
        self.key(self.pg.K_RETURN)
        self.await_request(lambda request: request.label == "Accept this background?")
        self.key(self.pg.K_1, "1")
        self.await_request(lambda request: request.label.startswith("What lesson"))
        self.assertIsNot(self.game.state, previous)
        self.assertEqual(self.window.hud["name"], "Aerin")
        self.assertFalse(any("private earlier discovery" in text for text, _, _ in self.window.history))
        self.assertEqual(self.window.archive.query, "")
        self.assertEqual(self.window.hud["hp"], self.game.state.character.hp)
        self.key(self.pg.K_1, "1")
        self.await_request(lambda request: request.kind == "pause")
        self.assertEqual(self.results, [True])
        self.assertEqual(self.window.hud["name"], "Aerin")
        self.assertTrue(any("Aerin's own road" in text for text, _, _ in self.window.history))

    def test_discovery_is_archived_once_and_survives_read_only_overlays(self):
        self.start()
        before = self.game.state.to_dict()
        look = next(look for look in WORLD_MAPS["bree"].looks if look.key == "pony_sign")
        rect = self.window.world._rect
        position = (rect.left + round(look.position[0] * rect.width / 320), rect.top + round(look.position[1] * rect.height / 240))
        self.window.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=position))
        for _ in range(150):
            self.window.world.update(0.05)
        self.key(self.pg.K_e, "e")
        self.assertEqual(self.window.world.inspection_title, look.name)
        self.assertEqual(sum(text == look.text for text, _, _ in self.window.history), 1)
        standing = self.window.world.player_position
        self.key(self.pg.K_TAB)
        self.window.render()
        self.window.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_f, mod=self.pg.KMOD_CTRL, unicode=""))
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="horse sign"))
        self.window.render()
        self.assertTrue(self.window.archive.matches)
        self.key(self.pg.K_TAB)
        self.window.render()
        self.assertEqual(self.window.world.inspection_title, look.name)
        self.key(self.pg.K_F1)
        self.key(self.pg.K_ESCAPE)
        self.window.render()
        self.assertEqual(self.window.world.inspection_title, look.name)
        self.key(self.pg.K_i, "i")
        self.await_request(lambda request: request.kind == "panel")
        self.key(self.pg.K_ESCAPE)
        self.await_request(lambda request: request.story)
        self.assertEqual(self.window.world.inspection_title, look.name)
        self.assertEqual(self.window.world.player_position, standing)
        self.key(self.pg.K_p, "p")
        self.await_request(lambda request: request.label == "JOURNEY PAUSED")
        self.key(self.pg.K_ESCAPE)
        self.await_request(lambda request: request.story)
        self.assertEqual(self.window.world.inspection_title, look.name)
        self.key(self.pg.K_e, "e")
        self.key(self.pg.K_e, "e")
        self.assertEqual(self.window.world.inspection_title, look.name)
        self.assertEqual(sum(text == look.text for text, _, _ in self.window.history), 1)
        self.assertEqual(self.game.state.to_dict(), before)
        self.assertEqual(self.results, [])
