"""Save-card identity and actions use actual engine slot summaries."""

from __future__ import annotations

from copy import deepcopy
import importlib.util
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.pixel_panels import PanelView
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.ui import TerminalUI


class _SlotCaptureUI(TerminalUI):
    def __init__(self):
        super().__init__(fast=True)
        self.snapshot = None

    def show_panel(self, kind, data):
        if kind != "saves":
            raise AssertionError("Expected an actual save-slot summary")
        self.snapshot = data
        return None


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for save-card rendering")
class SaveCardSDLTests(unittest.TestCase):
    def setUp(self):
        import pygame

        self.pg = pygame
        pygame.display.init()
        pygame.font.init()
        self.temporary = tempfile.TemporaryDirectory()
        self.manager = SaveManager(Path(self.temporary.name) / "saves")
        self.ui = _SlotCaptureUI()
        self.game = Game(self.ui, saves=self.manager)
        self.first = GameState(Character.from_origin("Mira Éowen", ORIGINS[0]),
                               scene="bree_exploration", play_minutes=37)
        self.first.character.hp = 22
        self.later = GameState(Character.from_origin("Saoirse Éowen", ORIGINS[1]),
                               scene="part2_vigil", chapter=2, play_minutes=132)
        self.later.character.hp = 19
        self.manager.save(1, self.first)
        self.manager.save(2, self.later)
        self.panel = PanelView(pygame)
        self.screen = pygame.Surface((1200, 900))
        self.rect = pygame.Rect(23, 75, 1154, 787)

    def tearDown(self):
        self.panel = self.screen = None
        self.pg.quit()
        self.temporary.cleanup()

    def snapshot(self, mode="load"):
        self.assertIsNone(self.game._choose_save_slot(mode))
        return deepcopy(self.ui.snapshot)

    def draw(self, *, preference="standard"):
        self.panel.draw(self.screen, self.rect, text_size=preference)

    def key(self, key):
        return self.panel.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=key, mod=0, unicode=""))

    def test_real_slot_summary_keeps_name_background_location_elapsed_time_and_timestamp(self):
        snapshot = self.snapshot()
        before = deepcopy(snapshot)
        self.panel.open("saves", snapshot)
        self.draw()
        first = [text for text, _, _ in self.panel._slot_lines(snapshot["slots"][0], "load")]
        later = [text for text, _, _ in self.panel._slot_lines(snapshot["slots"][1], "load")]
        self.assertIn("Part I / Bree", first)
        self.assertIn(ORIGINS[0].name, first)
        self.assertIn("Health 22/28 · Played 37 min", first)
        self.assertTrue(any(text.startswith("Saved ") for text in first))
        self.assertIn("Part II / The Last Lantern", later)
        self.assertIn(ORIGINS[1].name, later)
        self.assertIn("Health 19/25 · Played 2h 12m", later)
        self.assertEqual(snapshot, before)
        self.assertEqual(self.panel.data, before)
        self.assertEqual(self.manager.load(1).to_dict(), self.first.to_dict())
        self.assertEqual(self.manager.load(2).to_dict(), self.later.to_dict())

    def test_save_portraits_use_each_saved_background_instead_of_the_current_traveler(self):
        self.game.state = GameState(Character.from_origin("Current Healer", ORIGINS[2]))
        self.panel.open("saves", self.snapshot("save"))
        with patch.object(self.panel, "_identity_portrait", wraps=self.panel._identity_portrait) as portrait:
            self.draw()
        self.assertEqual([call.args[1] for call in portrait.call_args_list],
                         [ORIGINS[0].origin_id, ORIGINS[1].origin_id])
        self.assertTrue(all(call.args[2].size == (64, 80) for call in portrait.call_args_list))

    def test_empty_and_damaged_slots_load_disabled_but_remain_writable_after_selection(self):
        self.manager._path(2).write_text("damaged memory", encoding="utf-8")
        for mode in ("load", "save"):
            self.panel.open("saves", self.snapshot(mode))
            self.draw()
            for index in (1, 2):
                self.panel.selected = index
                self.panel._ensure_selection = True
                self.draw()
                action = self.key(self.pg.K_RETURN)
                expected = {"action": "select_slot", "slot": index + 1} if mode == "save" else None
                self.assertEqual(action, (True, expected))
                self.assertEqual(any(target == "slot_action" and value == index
                                     for _, target, value in self.panel.hit_targets), mode == "save")
            with patch.object(self.panel, "_save_identity", wraps=self.panel._save_identity) as portrait:
                self.draw()
            self.assertEqual(len(portrait.call_args_list), 1, "Empty or damaged memories received a portrait")

    def test_compact_every_text_size_keeps_selected_memory_and_action_readable(self):
        self.screen = self.pg.Surface((760, 560))
        self.rect = self.pg.Rect(23, 75, 714, 447)
        for preference in ("standard", "large", "larger"):
            for index in (0, 1, 2):
                with self.subTest(preference=preference, slot=index + 1):
                    self.panel.open("saves", self.snapshot("save"))
                    self.panel.selected = index
                    with patch.object(self.panel, "_text", wraps=self.panel._text) as text, patch.object(
                        self.panel, "_save_identity", wraps=self.panel._save_identity
                    ) as portraits:
                        self.draw(preference=preference)
                    action = next(rect for rect, target, value in self.panel.hit_targets
                                  if target == "slot_action" and value == index)
                    self.assertTrue(self.panel.content_rect.contains(action))
                    self.assertGreaterEqual(action.height, 35)
                    self.assertEqual(self.key(self.pg.K_RETURN),
                                     (True, {"action": "select_slot", "slot": index + 1}))
                    if index < 2:
                        identity = portraits.call_args_list[index].args[2]
                        self.assertTrue(self.panel.content_rect.contains(identity))
                        self.assertFalse(identity.colliderect(action))
                        name = self.panel.data["slots"][index]["name"]
                        names = [call for call in text.call_args_list if call.args[1] == name]
                        self.assertEqual(len(names), 1)
                        name_call = names[0]
                        font = name_call.kwargs["font"]
                        ink = font.render(name, False, (255, 255, 255)).get_bounding_rect().move(name_call.args[2:4])
                        self.assertTrue(self.panel.content_rect.contains(ink))

    def test_unknown_legacy_origin_and_invalid_optional_time_do_not_invent_a_preview(self):
        snapshot = self.snapshot()
        legacy = snapshot["slots"][0]
        legacy["origin"] = "an_old_background"
        legacy["play_minutes"] = "not a duration"
        legacy["saved_at"] = "not a timestamp"
        self.panel.open("saves", {"mode": "load", "slots": [legacy]})
        with patch.object(self.panel, "_identity_portrait", wraps=self.panel._identity_portrait) as portrait:
            self.draw()
        portrait.assert_not_called()
        lines = [text for text, _, _ in self.panel._slot_lines(legacy, "load")]
        self.assertIn("Part I / Bree", lines)
        self.assertIn("Health 22/28", lines)
        self.assertFalse(any("Played" in text or text.startswith("Saved ") for text in lines))
        self.assertEqual(self.key(self.pg.K_RETURN), (True, {"action": "select_slot", "slot": 1}))

    def test_resize_and_text_reflow_keep_the_selected_saved_journey_visible(self):
        self.panel.open("saves", self.snapshot("save"))
        self.panel.selected = 1
        for size, preference in (((1200, 900), "standard"), ((760, 560), "larger"),
                                 ((1200, 900), "large"), ((760, 560), "standard")):
            with self.subTest(size=size, preference=preference):
                self.screen = self.pg.Surface(size)
                self.rect = self.pg.Rect(23, 75, size[0] - 46, size[1] - 113)
                self.draw(preference=preference)
                action = next(rect for rect, target, value in self.panel.hit_targets
                              if target == "slot_action" and value == 1)
                self.assertTrue(self.panel.content_rect.contains(action))
                self.assertEqual(self.panel.selected, 1)
                self.assertEqual(self.key(self.pg.K_RETURN), (True, {"action": "select_slot", "slot": 2}))

    def test_completed_late_episode_summary_remembers_the_saved_location_only(self):
        ending = GameState(Character.from_origin("Last Warden", ORIGINS[2]), scene="complete",
                           chapter=2, ending="living_road", play_minutes=240)
        self.manager.save(2, ending)
        self.panel.open("saves", self.snapshot())
        self.draw(preference="larger")
        lines = [text for text, _, _ in self.panel._slot_lines(self.panel.data["slots"][1], "load")]
        self.assertIn("Part II complete / The Road Ahead", lines)
        self.assertIn("Health 23/23 · Played 4h 00m", lines)
        self.assertFalse(any("living_road" in text or "Hidden Road" in text for text in lines))
        self.assertEqual(self.panel.data["slots"][1]["scene"], "complete")

    def test_portrait_cache_stays_bounded_and_warm_redraws_perform_no_image_io(self):
        third = GameState(Character.from_origin("Healer", ORIGINS[2]), scene="part2_house_under_ash", chapter=2)
        self.manager.save(3, third)
        self.panel.open("saves", self.snapshot())
        self.draw()
        keys = set(self.panel._portraits)
        self.assertEqual(len(keys), 3)
        for size in ((760, 560), (1000, 700), (1400, 1000), (1920, 1080)):
            self.screen = self.pg.Surface(size)
            self.rect = self.pg.Rect(23, 75, size[0] - 46, size[1] - 113)
            with patch.object(self.pg.image, "load", side_effect=AssertionError("A warm save card opened an image again")):
                self.draw(preference="larger")
                self.draw(preference="standard")
            self.assertEqual(set(self.panel._portraits), keys)

    def test_missing_portrait_resources_fall_back_once_and_keep_loading_available(self):
        self.panel.open("saves", self.snapshot())
        with patch.object(self.pg.image, "load", side_effect=self.pg.error("Missing optional portrait")) as load:
            self.draw()
            first_calls = load.call_count
            self.assertGreater(first_calls, 0)
            self.draw()
            self.assertEqual(load.call_count, first_calls)
        self.assertEqual(self.key(self.pg.K_RETURN), (True, {"action": "select_slot", "slot": 1}))

    def test_malformed_face_sheet_uses_existing_world_identity_without_reloading(self):
        self.panel.open("saves", self.snapshot())
        original = self.pg.image.load
        def load(path):
            if str(path).endswith("world-origin-portraits.png"):
                return self.pg.Surface((10, 10))
            return original(path)
        with patch.object(self.pg.image, "load", side_effect=load) as image:
            self.draw()
            calls = image.call_count
            self.draw()
            self.assertEqual(image.call_count, calls)
        self.assertEqual(self.key(self.pg.K_RETURN), (True, {"action": "select_slot", "slot": 1}))

    def test_narrow_cards_keep_their_full_text_column_and_bottom_actions(self):
        self.screen = self.pg.Surface((520, 620))
        self.rect = self.pg.Rect(15, 20, 490, 580)
        self.panel.open("saves", self.snapshot("save"))
        self.panel.selected = 1
        with patch.object(self.panel, "_save_identity", wraps=self.panel._save_identity) as portrait:
            self.draw(preference="larger")
        portrait.assert_not_called()
        self.assertTrue(any(target == "slot_action" and value == 1 for _, target, value in self.panel.hit_targets))
        self.assertEqual(self.key(self.pg.K_RETURN), (True, {"action": "select_slot", "slot": 2}))


if __name__ == "__main__":
    unittest.main()
