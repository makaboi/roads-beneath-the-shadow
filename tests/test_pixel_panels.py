"""Modal snapshots and SDL interaction must preserve the story's authority."""

import importlib.util
import os
import unittest
from copy import deepcopy
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from roads_beneath_shadow.pixel_panels import PanelView, _wrap
from roads_beneath_shadow.content import ORIGINS, QUEST_REACH_CALENOR
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.player_view import background_snapshot, chronicle_snapshot, player_snapshot
from roads_beneath_shadow.profile import PlayerProfile


SNAPSHOT = {
    "character": {
        "name": "Éowen",
        "origin_label": "Bree Watch deserter",
        "origin_description": "You know the lanes around Bree, and which promises the watch failed to keep.",
        "hp": 18, "max_hp": 26, "focus": 2, "max_focus": 3,
        "hope": 4, "corruption": 1, "strength": 3, "cunning": 2, "will": 3,
        "gear": {"weapon": "Bree-forged Sword", "armor": "Patched Leather"},
        "ability_name": "Hold the line",
        "ability_description": "Stand firm when the road turns against you.",
    },
    "items": [
        {"id": "letter", "name": "Calenor's Sealed Letter", "description": "Rain-stained, but its black wax seal is intact.", "kind": "quest", "count": 1},
        {"id": "blade", "name": "Bree-forged Sword", "description": "Plain steel with a dependable edge.", "kind": "weapon", "slot": "weapon", "attack": 4, "defense": 0, "count": 1, "equipped": True},
        {"id": "cleaver", "name": "Orc Cleaver", "description": "Ugly iron, balanced for brutal cuts.", "kind": "weapon", "slot": "weapon", "attack": 5, "defense": 0, "count": 1, "equipped": False},
        {"id": "leather", "name": "Patched Leather", "description": "Old armor that still turns a glancing blow.", "kind": "armor", "slot": "armor", "defense": 1, "count": 1, "equipped": True},
        {"id": "herb", "name": "Healing Herb", "description": "A wrapped bundle of yarrow and athelas.", "kind": "consumable", "healing": 9, "count": 3},
        {"id": "smoke", "name": "Dwarf-smoke Flask", "description": "A smoke flask to break an enemy's pursuit.", "kind": "consumable", "healing": 0, "count": 1},
    ],
    "companions": [{"name": "Mara", "trust": 3, "present": True}, {"name": "Tobin", "trust": -1, "present": False}],
    "activequests": [{"title": "Carry Calenor's warning east", "description": "Find the old wayhouse beyond Bree before the riders reach it."}, "Learn what the broken star opens"],
    "completedquests": ["Escape the Prancing Pony"],
    "clues": ["The black arrowhead bears the mark of a lidless red eye.", "Mara recognized the pendant before she admitted knowing Calenor."],
}


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for panel SDL tests")
class PixelPanelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pygame
        cls.pg = pygame
        pygame.init()

    @classmethod
    def tearDownClass(cls):
        cls.pg.quit()

    def setUp(self):
        self.panel = PanelView(self.pg)
        self.screen = self.pg.Surface((1100, 800))
        self.rect = self.screen.get_rect()

    def draw(self):
        self.panel.draw(self.screen, self.rect)

    def key(self, key, *, mod=0):
        return self.panel.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=key, mod=mod, unicode=""))

    def click(self, target, value=None):
        rect = next(rect for rect, name, result in self.panel.hit_targets if name == target and (value is None or result == value))
        return self.panel.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=rect.center))

    def select_item(self, item_id):
        self.panel.selected = next(index for index, item in enumerate(self.panel.visible_items()) if item["id"] == item_id)
        self.panel._ensure_selection = True
        self.draw()

    def test_face_portraits_show_the_chosen_background_and_stay_inside_their_tile(self):
        from roads_beneath_shadow.pixel_theme import ORIGIN_PORTRAIT_FILE
        atlas = self.pg.image.load(str(ORIGIN_PORTRAIT_FILE))
        sentinel = (243, 12, 231, 255)
        for index, origin in enumerate(ORIGINS):
            for scale in (1, 2):
                with self.subTest(origin=origin.origin_id, scale=scale):
                    tile = self.pg.Rect(17, 21, 64 * scale, 80 * scale)
                    surface = self.pg.Surface((180, 210), self.pg.SRCALPHA)
                    expected = surface.copy()
                    surface.fill(sentinel)
                    expected.fill(sentinel)
                    face = atlas.subsurface((index * 64, 0, 64, 80))
                    expected.blit(self.pg.transform.scale(face, tile.size), tile)
                    self.assertTrue(self.panel._identity_portrait(surface, origin.origin_id, tile))
                    self.assertEqual(self.pg.image.tobytes(surface, "RGBA"), self.pg.image.tobytes(expected, "RGBA"))

    def test_missing_or_malformed_face_sheet_falls_back_to_the_world_identity(self):
        tile = self.pg.Rect(13, 15, 64, 80)
        for failure in (OSError("missing optional portrait"), self.pg.Surface((10, 10))):
            with self.subTest(failure=type(failure).__name__):
                panel = PanelView(self.pg)
                surface = self.pg.Surface((100, 110), self.pg.SRCALPHA)
                surface.fill((0, 0, 0, 0))
                real_load = self.pg.image.load
                def load(path):
                    if str(path).endswith("world-origin-portraits.png"):
                        if isinstance(failure, BaseException):
                            raise failure
                        return failure
                    return real_load(path)
                with patch.object(self.pg.image, "load", side_effect=load):
                    self.assertTrue(panel._identity_portrait(surface, "north_road_scout", tile))
                self.assertTrue(tile.contains(surface.get_bounding_rect()))
                self.assertGreater(surface.get_bounding_rect().width, 0)

    def test_unknown_background_uses_generic_traveler_instead_of_another_origin_face(self):
        with patch.object(self.panel, "_origin_portrait", return_value=True) as fallback:
            self.assertTrue(self.panel._identity_portrait(self.screen, "unknown_origin", self.pg.Rect(0, 0, 64, 80)))
        fallback.assert_called_once()
        self.assertEqual(fallback.call_args.args[1], "unknown_origin")

    def test_companion_portraits_keep_the_right_cast_identity_and_existing_bounds(self):
        from pathlib import Path
        import roads_beneath_shadow.pixel_panels as panels
        atlas = self.pg.image.load(str(Path(panels.__file__).with_name("pixel_assets") / "world-battle-cast.png"))
        for index, name in enumerate(("Mara", "Tobin", "Calenor")):
            with self.subTest(name=name):
                tile = self.pg.Rect(17, 21, 40, 48)
                surface = self.pg.Surface((90, 90), self.pg.SRCALPHA)
                expected = surface.copy()
                surface.fill((243, 12, 231, 255))
                expected.fill((243, 12, 231, 255))
                expected.blit(atlas.subsurface((index * 40, 48, 40, 48)), tile)
                self.assertTrue(self.panel._companion_portrait(surface, name, tile.x, tile.y))
                self.assertEqual(self.pg.image.tobytes(surface, "RGBA"), self.pg.image.tobytes(expected, "RGBA"))

    def test_missing_or_malformed_companion_sheet_preserves_legacy_identity(self):
        for failure in (OSError("missing optional companion cast"), self.pg.Surface((10, 10))):
            for name, row in (("Mara", 4), ("Tobin", 5), ("Calenor", 6)):
                with self.subTest(failure=type(failure).__name__, name=name):
                    panel = PanelView(self.pg)
                    real_load = self.pg.image.load
                    def load(path):
                        if str(path).endswith("world-battle-cast.png"):
                            if isinstance(failure, BaseException):
                                raise failure
                            return failure
                        return real_load(path)
                    with patch.object(self.pg.image, "load", side_effect=load), patch.object(panel, "_portrait", wraps=panel._portrait) as legacy:
                        self.assertTrue(panel._companion_portrait(self.screen, name, 17, 21))
                    legacy.assert_called_once_with(self.screen, row, 17, 21, 2)

    def test_largest_text_save_caption_is_complete_inside_its_clickable_button(self):
        panel = self.panel
        screen = self.pg.Surface((760, 560))
        panel.open("saves", {"mode": "save", "slots": [
            {"slot": 1, "empty": False, "name": "Éowen", "chapter": 1, "location": "Bree", "hp": 18, "max_hp": 26},
            {"slot": 2, "empty": True},
        ]})
        labels = []
        original = panel._button
        def button(surface, rect, label, target, value=None, **kwargs):
            font = panel._button_font(label, rect)
            ink = font.render(label, False, (255, 255, 255))
            self.assertLessEqual(ink.get_width(), rect.width - 12, label)
            self.assertLessEqual(ink.get_height(), rect.height - 6, label)
            labels.append(label)
            return original(surface, rect, label, target, value, **kwargs)
        panel._button = button
        panel.draw(screen, self.pg.Rect(18, 68, 724, 445), text_size="larger")
        self.assertIn("Overwrite...", labels)
        self.assertEqual(self.click("slot_action", 0), (True, {"action": "select_slot", "slot": 1}))

    def test_compact_largest_character_keeps_health_and_focus_visible_with_long_names(self):
        screen = self.pg.Surface((760, 560))
        overlay = self.pg.Rect(18, 68, 724, 445)
        for origin in ORIGINS:
            with self.subTest(origin=origin.origin_id):
                state = GameState(Character.from_origin("É" * 24, origin))
                panel = PanelView(self.pg)
                meters = []
                original = panel._meter
                def meter(surface, label, value, maximum, x, y, width, color):
                    meters.append((label, self.pg.Rect(x, y + panel.line_height, width, 11)))
                    return original(surface, label, value, maximum, x, y, width, color)
                panel._meter = meter
                panel.open("character", player_snapshot(state))
                panel.draw(screen, overlay, text_size="larger")
                self.assertEqual([label for label, _ in meters], ["Health", "Focus"])
                for label, rect in meters:
                    self.assertTrue(panel.content_rect.contains(rect), label)
                close = next(rect for rect, target, _ in panel.hit_targets if target == "close")
                self.assertTrue(overlay.contains(close))
                self.assertEqual(panel.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=close.center)), (True, {"action": "close"}))

    def test_open_owns_a_deep_snapshot_and_actions_do_not_mutate_it(self):
        supplied = deepcopy(SNAPSHOT)
        self.panel.open("inventory", supplied)
        supplied["items"][2]["name"] = "Changed outside panel"
        supplied["character"]["hp"] = 0
        self.assertEqual(self.panel.data["items"][2]["name"], "Orc Cleaver")
        self.assertEqual(self.panel.data["character"]["hp"], 18)
        before = deepcopy(self.panel.data)
        self.select_item("cleaver")
        self.assertEqual(self.key(self.pg.K_RETURN), (True, {"action": "equip", "item_id": "cleaver"}))
        self.assertEqual(self.panel.data, before)

    def test_inventory_is_sorted_and_tab_filters_preserve_item_identity(self):
        self.panel.open("inventory", SNAPSHOT)
        self.assertEqual([item["id"] for item in self.panel.visible_items()], ["blade", "cleaver", "leather", "smoke", "herb", "letter"])
        self.key(self.pg.K_TAB)
        self.assertEqual(self.panel.tab, "gear")
        self.assertEqual([item["id"] for item in self.panel.visible_items()], ["blade", "cleaver", "leather"])
        self.key(self.pg.K_RIGHT)
        self.assertEqual(self.panel.tab, "supplies")
        self.key(self.pg.K_TAB, mod=self.pg.KMOD_SHIFT)
        self.assertEqual(self.panel.tab, "gear")

    def test_click_selects_item_then_returns_the_corresponding_engine_action(self):
        self.panel.open("inventory", SNAPSHOT)
        self.draw()
        self.assertEqual(self.click("item", 1), (True, None))
        self.draw()
        self.assertEqual(self.click("item_action"), (True, {"action": "equip", "item_id": "cleaver"}))
        self.assertFalse(self.panel.data["items"][2]["equipped"])

    def test_healing_is_actionable_but_equipped_gear_and_combat_supplies_are_not(self):
        self.panel.open("inventory", SNAPSHOT)
        self.select_item("herb")
        self.assertEqual(self.key(self.pg.K_RETURN), (True, {"action": "use", "item_id": "herb"}))
        for item_id in ("blade", "smoke", "letter"):
            self.select_item(item_id)
            self.assertEqual(self.key(self.pg.K_RETURN), (True, None))
            self.assertFalse(any(target == "item_action" for _, target, _ in self.panel.hit_targets))

    def test_zero_quantity_cannot_produce_a_consumption_or_equip_action(self):
        supplied = deepcopy(SNAPSHOT)
        supplied["items"][4]["count"] = 0
        self.panel.open("inventory", supplied)
        self.select_item("herb")
        self.assertEqual(self.key(self.pg.K_RETURN), (True, None))

    def test_inventory_end_scrolls_to_a_long_item_without_losing_its_id(self):
        supplied = deepcopy(SNAPSHOT)
        supplied["items"] += [
            {"id": f"quest_{index}", "name": f"Z{index:02d} " + "A very long keepsake name " * 5, "description": "A note.", "kind": "quest", "count": 1}
            for index in range(20)
        ]
        self.panel.open("inventory", supplied)
        self.draw()
        self.key(self.pg.K_END)
        self.draw()
        self.assertGreater(self.panel.scroll, 0)
        self.assertEqual(self.panel._selected_item()["id"], "quest_19")
        selected_hit = next(rect for rect, kind, value in self.panel.hit_targets if kind == "item" and value == self.panel.selected)
        self.assertGreater(selected_hit.height, 0)
        self.assertTrue(self.panel.content_rect.contains(selected_hit))

    def test_long_description_scrolls_while_its_action_stays_reachable(self):
        supplied = deepcopy(SNAPSHOT)
        supplied["items"][2]["description"] = "Old roads remember every footstep. " * 100
        self.panel.open("inventory", supplied)
        self.select_item("cleaver")
        self.assertGreater(self.panel.max_detail_scroll, 0)
        action_rect = next(rect for rect, target, _ in self.panel.hit_targets if target == "item_action")
        self.assertTrue(self.panel.detail_rect.contains(action_rect))
        self.assertFalse(action_rect.colliderect(self.panel.detail_body_rect))
        self.key(self.pg.K_PAGEDOWN, mod=self.pg.KMOD_SHIFT)
        self.assertGreater(self.panel.detail_scroll, 0)
        self.panel.detail_scroll = self.panel.max_detail_scroll
        self.draw()
        self.assertEqual(self.click("item_action"), (True, {"action": "equip", "item_id": "cleaver"}))

    def test_character_journal_and_map_are_scrollable_and_return_explicitly(self):
        supplied = deepcopy(SNAPSHOT)
        supplied["activequests"] *= 10
        supplied["companions"] *= 6
        supplied["route"] = [{"name": f"Road {index}", "visited": index < 8, "current": index == 8} for index in range(20)]
        for kind in ("character", "journal", "map"):
            self.panel.open(kind, supplied)
            if kind == "map":
                self.key(self.pg.K_TAB)
            self.draw()
            self.assertGreater(self.panel.max_scroll, 0, kind)
            self.key(self.pg.K_END)
            self.draw()
            self.assertEqual(self.panel.scroll, self.panel.max_scroll)
            self.assertEqual(self.key(self.pg.K_RETURN), (True, {"action": "close"}))
            self.assertFalse(self.panel.active)

    def test_character_fate_cards_show_recorded_whereabouts_and_close_without_changing_the_journey(self):
        state = GameState(Character.from_origin("Mira", ORIGINS[1]), scene="complete", chapter=2)
        state.completed_quests.append(QUEST_REACH_CALENOR)
        state.flags.update({"part2_mara_left": True, "tobin_stays_at_threshold": True, "part2_calenor_rebound": True})
        before = state.to_dict()
        drawn = []
        paragraph = self.panel._paragraph

        def capture(screen, text, *args, **kwargs):
            drawn.append(str(text))
            return paragraph(screen, text, *args, **kwargs)

        self.panel._paragraph = capture
        for size in ((760, 560), (1920, 1080)):
            with self.subTest(size=size):
                self.screen = self.pg.Surface(size)
                self.rect = self.screen.get_rect()
                self.panel.open("character", player_snapshot(state))
                self.panel.draw(self.screen, self.rect, text_size="larger")
                self.key(self.pg.K_END)
                self.panel.draw(self.screen, self.rect, text_size="larger")
                for fact in ("Left at the burned refuge to seek the prisoners", "Remained at the threshold with Ned's lantern", "Bound again at the Last Seal"):
                    self.assertTrue(any(fact in text for text in drawn), fact)
                self.assertFalse(any("Elsewhere on the road" in text for text in drawn))
                self.assertEqual(self.click("close"), (True, {"action": "close"}))
                self.assertEqual(state.to_dict(), before)

    def test_journal_tabs_show_active_completed_and_clues_with_aliases(self):
        self.panel.open("journal", {"active_quests": ["Active"], "completed_quests": ["Done"], "journal": ["Clue"]})
        self.assertEqual(self.panel._journal_entries(), ["Active"])
        self.key(self.pg.K_TAB)
        self.assertEqual(self.panel._journal_entries(), ["Done"])
        self.key(self.pg.K_TAB)
        self.assertEqual(self.panel._journal_entries(), ["Clue"])

    def test_escape_and_return_button_close_without_reaching_underlying_choices(self):
        self.panel.open("journal", SNAPSHOT)
        self.draw()
        self.assertEqual(self.click("close"), (True, {"action": "close"}))
        self.assertFalse(self.panel.active)
        self.panel.open("inventory", SNAPSHOT)
        self.assertEqual(self.key(self.pg.K_ESCAPE), (True, {"action": "close"}))
        self.assertEqual(self.key(self.pg.K_RETURN), (False, None))

    def test_modal_consumes_story_shortcuts_and_text_but_passes_window_lifecycle(self):
        self.panel.open("inventory", SNAPSHOT)
        self.assertEqual(self.key(self.pg.K_1), (True, None))
        self.assertEqual(self.key(self.pg.K_s), (True, None))
        self.assertEqual(self.panel.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="S")), (True, None))
        self.assertEqual(self.panel.handle_event(self.pg.event.Event(self.pg.QUIT)), (False, None))
        self.assertEqual(self.key(self.pg.K_F11), (False, None))

    def test_save_slots_require_a_real_memory_for_loading_and_return_slot_identity(self):
        slots = [{"slot": 1, "empty": True}, {"slot": 7, "name": "Éowen", "chapter": 2, "play_minutes": 91, "empty": False}]
        self.panel.open("saves", {"mode": "load", "slots": slots})
        self.draw()
        self.assertEqual(self.key(self.pg.K_RETURN), (True, None))
        self.key(self.pg.K_DOWN)
        self.draw()
        self.assertEqual(self.key(self.pg.K_RETURN), (True, {"action": "select_slot", "slot": 7}))
        self.panel.open("saves", {"mode": "save", "slots": slots})
        self.draw()
        self.assertEqual(self.click("slot_action", 0), (True, {"action": "select_slot", "slot": 1}))

    def test_save_end_navigation_reveals_selected_slot(self):
        self.panel.open("saves", {"mode": "save", "slots": [{"slot": index + 1, "empty": True} for index in range(20)]})
        self.draw()
        self.key(self.pg.K_END)
        self.draw()
        self.assertGreater(self.panel.scroll, 0)
        self.assertTrue(any(target == "slot" and value == 19 for _, target, value in self.panel.hit_targets))
        self.assertEqual(self.key(self.pg.K_RETURN), (True, {"action": "select_slot", "slot": 20}))

    def test_damaged_saves_cannot_load_with_keyboard_or_mouse(self):
        slots = [{"slot": 2, "corrupt": True, "empty": False}, {"slot": 3, "name": "Éowen", "chapter": 2, "empty": False}]
        self.panel.open("saves", {"mode": "load", "slots": slots})
        self.draw()
        self.assertEqual(self.key(self.pg.K_RETURN), (True, None))
        self.assertFalse(any(target == "slot_action" and index == 0 for _, target, index in self.panel.hit_targets))
        self.assertEqual(self.click("slot", 0), (True, None))
        self.assertEqual(self.key(self.pg.K_SPACE), (True, None))
        self.key(self.pg.K_DOWN)
        self.draw()
        self.assertEqual(self.click("slot_action", 1), (True, {"action": "select_slot", "slot": 3}))

    def test_damaged_slot_can_be_selected_for_engine_confirmed_overwrite(self):
        slots = [{"slot": 2, "corrupt": True, "empty": False}]
        self.panel.open("saves", {"mode": "save", "slots": slots})
        self.draw()
        self.assertEqual(self.click("slot_action", 0), (True, {"action": "select_slot", "slot": 2}))
        self.assertTrue(self.panel.data["slots"][0]["corrupt"])

    def test_empty_panels_resize_without_crashing_and_restore_the_callers_clip(self):
        for size in ((760, 600), (1100, 800), (1400, 1000)):
            screen = self.pg.Surface(size)
            original_clip = self.pg.Rect(5, 5, size[0] - 10, size[1] - 10)
            screen.set_clip(original_clip)
            for kind in ("inventory", "character", "journal", "map", "saves", "chronicle", "information"):
                self.panel.open(kind, {})
                self.panel.draw(screen, screen.get_rect())
                self.assertEqual(screen.get_clip(), original_clip)
                self.key(self.pg.K_DOWN)
                self.key(self.pg.K_END)
                self.panel.draw(screen, screen.get_rect())
                self.assertTrue(self.panel.active)

    def test_chronicle_scrolls_to_last_achievement_and_preserves_earned_state(self):
        snapshot = chronicle_snapshot(PlayerProfile(
            completed_runs=5, origins_completed=["bree_wayfarer"],
            endings={"fellowship": 4, "living_road": 1}, achievements=["part_one", "part_two"],
        ))
        self.panel.open("chronicle", snapshot)
        before = deepcopy(self.panel.data)
        visible = []
        original_text = self.panel._text

        def record_visible(screen, text, x, y, *args, **kwargs):
            if self.panel.content_rect.collidepoint(x, y):
                visible.append(str(text))
            return original_text(screen, text, x, y, *args, **kwargs)

        self.panel._text = record_visible
        self.draw()
        self.assertGreater(self.panel.max_scroll, 0)
        self.assertIn("Completed episodes: 5", visible)
        visible.clear()
        self.key(self.pg.K_END)
        self.draw()
        self.assertEqual(self.panel.scroll, self.panel.max_scroll)
        self.assertIn("No Name for the Shadow", visible)
        self.assertIn("UNDISCOVERED", visible)
        self.assertNotIn("Completed episodes: 5", visible)
        self.assertEqual(self.panel.data, before)
        self.assertEqual(self.key(self.pg.K_ESCAPE), (True, {"action": "close"}))

    def test_enemy_information_preserves_long_notes_and_scrolls_back_to_battle(self):
        notes = "A blinded troll listens for chains in the dark. " * 70
        snapshot = {"title": "Chain Troll", "subtitle": "Enemy inspection / no turn spent", "sections": [
            {"heading": "Defenses", "text": "Health 30/30. Armor 3. Phase 1."},
            {"heading": "Field notes", "text": notes},
        ]}
        self.panel.open("information", snapshot)
        self.draw()
        self.assertGreater(self.panel.max_scroll, 0)
        self.key(self.pg.K_END)
        self.draw()
        self.assertEqual(self.panel.scroll, self.panel.max_scroll)
        self.assertEqual(self.panel.data["sections"][1]["text"], notes)
        self.assertEqual(self.key(self.pg.K_RETURN), (True, {"action": "close"}))

    def test_wrapping_preserves_unicode_and_very_long_unbroken_names(self):
        for source in ("Éowen's road through the forgotten wayhouse", "É" * 90):
            lines = _wrap(source, self.panel.font, 70)
            self.assertTrue(all(self.panel.font.size(line)[0] <= 70 for line in lines))
            self.assertEqual("".join(lines).replace(" ", ""), source.replace(" ", ""))

    def test_inventory_action_is_visible_at_the_actual_minimum_overlay_size(self):
        self.panel.open("inventory", SNAPSHOT)
        self.panel.selected = 1
        screen = self.pg.Surface((760, 560))
        overlay = self.pg.Rect(23, 75, 714, 447)
        self.panel.draw(screen, overlay)
        rect = next(rect for rect, target, _ in self.panel.hit_targets if target == "item_action")
        self.assertTrue(overlay.contains(rect))
        self.assertTrue(self.panel.detail_rect.contains(rect))
        self.assertEqual(self.panel.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=rect.center)), (True, {"action": "equip", "item_id": "cleaver"}))

    def test_full_health_disables_healing_with_keyboard_and_pointer(self):
        supplied = deepcopy(SNAPSHOT)
        supplied["character"]["hp"] = supplied["character"]["max_hp"]
        self.panel.open("inventory", supplied)
        self.select_item("herb")
        self.assertEqual(self.key(self.pg.K_RETURN), (True, None))
        self.assertEqual(self.panel._recovery_amount(self.panel._selected_item()), 0)
        self.assertFalse(any(target == "item_action" for _, target, _ in self.panel.hit_targets))
        self.assertEqual(self.panel.data["items"][4]["count"], 3)

    def test_inventory_filter_and_item_survive_engine_refresh_and_last_stack_removal(self):
        supplied = deepcopy(SNAPSHOT)
        supplied["journey_id"] = "first-journey"
        self.panel.open("inventory", supplied)
        self.key(self.pg.K_TAB)
        self.key(self.pg.K_TAB)
        self.select_item("herb")
        self.panel.close()
        supplied["items"][4]["count"] -= 1
        supplied["character"]["hp"] += 2
        self.panel.open("inventory", supplied)
        self.assertEqual(self.panel.tab, "supplies")
        self.assertEqual(self.panel._selected_item()["id"], "herb")
        self.assertEqual(self.panel._selected_item()["count"], 2)
        self.panel.close()
        supplied["items"] = [item for item in supplied["items"] if item["id"] != "herb"]
        self.panel.open("inventory", supplied)
        self.assertEqual(self.panel.tab, "supplies")
        self.assertEqual(self.panel._selected_item()["id"], "smoke")
        self.panel.close()
        supplied["journey_id"] = "a-new-journey"
        self.panel.open("inventory", supplied)
        self.assertEqual(self.panel.tab, "all")
        self.assertEqual(self.panel.selected, 0)

    def test_current_decision_is_read_only_in_journal_and_map(self):
        supplied = deepcopy(SNAPSHOT)
        supplied.update({"location": "Bree", "chapter": 1, "decision": {"heading": "WHERE WILL YOU INVESTIGATE?", "options": ["Search the stable yard", "Go to the north gate"]}})
        for kind in ("journal", "map"):
            self.panel.open(kind, supplied)
            if kind == "journal":
                for _ in range(3):
                    self.key(self.pg.K_TAB)
            self.draw()
            self.assertFalse(any(target not in {"tab", "close"} for _, target, _ in self.panel.hit_targets))
            self.assertEqual(self.key(self.pg.K_2), (True, None))
            self.assertTrue(self.panel.active)
            self.assertEqual(self.key(self.pg.K_ESCAPE), (True, {"action": "close"}))

    def test_chronicle_filters_earned_and_open_deeds_without_changing_profile(self):
        supplied = chronicle_snapshot(PlayerProfile(completed_runs=1, achievements=["part_one"], endings={"fellowship": 1}))
        self.panel.open("chronicle", supplied)
        self.key(self.pg.K_TAB)
        self.draw()
        self.assertEqual(self.panel.tab, "earned")
        before = deepcopy(self.panel.data)
        self.key(self.pg.K_TAB)
        self.draw()
        self.assertEqual(self.panel.tab, "open")
        self.assertEqual(self.panel.data, before)

    def test_chronicle_filters_show_deeds_immediately_at_minimum_window_size(self):
        supplied = chronicle_snapshot(PlayerProfile(completed_runs=2, origins_completed=["healers_apprentice"], achievements=["part_one"], endings={"fellowship": 1, "living_road": 1}))
        self.screen = self.pg.Surface((760, 560))
        self.rect = self.pg.Rect(23, 75, 714, 447)
        visible = []
        original_text = self.panel._text

        def record_visible(screen, text, x, y, *args, **kwargs):
            if self.panel.content_rect.collidepoint(x, y):
                visible.append(str(text))
            return original_text(screen, text, x, y, *args, **kwargs)

        self.panel._text = record_visible
        self.panel.open("chronicle", supplied)
        self.key(self.pg.K_TAB)
        self.draw()
        self.assertIn("The Road Opens", visible)
        self.assertNotIn("Completed episodes: 2", visible)
        visible.clear()
        self.key(self.pg.K_TAB)
        self.draw()
        self.assertIn("None Left Behind", visible)
        self.assertEqual(self.panel.scroll, 0)

    def test_unreadable_chronicle_notice_is_visible_on_every_section(self):
        supplied = chronicle_snapshot(PlayerProfile())
        supplied["notice"] = "The Chronicle could not be read. Its existing file has been kept; your journey saves are still available."
        self.screen = self.pg.Surface((760, 560))
        self.rect = self.pg.Rect(23, 75, 714, 447)
        visible = []
        original_text = self.panel._text

        def record_visible(screen, text, x, y, *args, **kwargs):
            if self.panel.content_rect.collidepoint(x, y):
                visible.append(str(text))
            return original_text(screen, text, x, y, *args, **kwargs)

        self.panel._text = record_visible
        self.panel.open("chronicle", supplied)
        for _ in range(3):
            visible.clear()
            self.draw()
            self.assertIn(supplied["notice"], " ".join(visible))
            self.assertTrue(any(target == "close" for _, target, _ in self.panel.hit_targets))
            self.key(self.pg.K_TAB)

    def test_scrollbar_track_click_and_thumb_drag_reach_the_same_text_as_keyboard(self):
        supplied = deepcopy(SNAPSHOT)
        supplied["clues"] = [f"Recorded note {index}: " + "Old roads remember. " * 4 for index in range(40)]
        self.panel.open("journal", supplied)
        self.key(self.pg.K_TAB)
        self.key(self.pg.K_TAB)
        self.draw()
        track, thumb, maximum = self.panel._scrollbars["main"]
        self.panel.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=(track.centerx, thumb.centery)))
        self.panel.handle_event(self.pg.event.Event(self.pg.MOUSEMOTION, pos=(track.centerx, track.bottom + 100), rel=(0, 100), buttons=(1, 0, 0)))
        self.assertEqual(self.panel.scroll, maximum)
        self.panel.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONUP, button=1, pos=(track.centerx, track.bottom)))
        self.assertIsNone(self.panel._dragging)
        self.draw()
        self.key(self.pg.K_HOME)
        self.assertEqual(self.panel.scroll, 0)
        self.draw()
        track, thumb, maximum = self.panel._scrollbars["main"]
        self.panel.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=(track.centerx, track.bottom - 2)))
        self.assertGreater(self.panel.scroll, maximum // 2)
        self.panel.handle_event(self.pg.event.Event(self.pg.WINDOWFOCUSLOST))
        self.assertIsNone(self.panel._dragging)

    def test_inventory_detail_rail_does_not_move_pack_selection(self):
        supplied = deepcopy(SNAPSHOT)
        supplied["items"][2]["description"] = "Old roads remember every footstep. " * 100
        self.panel.open("inventory", supplied)
        self.select_item("cleaver")
        before = self.panel.selected
        track, thumb, maximum = self.panel._scrollbars["detail"]
        self.panel.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=(track.centerx, track.bottom - 2)))
        self.assertGreater(self.panel.detail_scroll, maximum // 2)
        self.assertEqual(self.panel.selected, before)
        self.assertEqual(self.panel.scroll, 0)

    def test_resizing_a_journal_at_its_end_draws_the_last_clue_immediately(self):
        self.panel.open("journal", {"clues": [f"NOTE {index}: " + "This recorded clue remembers the road and the silver star. " * 12 for index in range(30)]})
        self.panel.tab_index = 2
        self.screen = self.pg.Surface((760, 560))
        self.rect = self.pg.Rect(23, 75, 714, 447)
        self.draw()
        self.key(self.pg.K_END)
        self.draw()
        old_scroll = self.panel.scroll
        self.screen = self.pg.Surface((1920, 1080))
        self.rect = self.pg.Rect(23, 75, 1874, 967)
        visible = []
        original_text = self.panel._text

        def record_visible(screen, text, x, y, *args, **kwargs):
            if self.panel.content_rect.collidepoint(x, y):
                visible.append(str(text))
            return original_text(screen, text, x, y, *args, **kwargs)

        self.panel._text = record_visible
        self.draw()
        self.assertLess(self.panel.scroll, old_scroll)
        self.assertEqual(self.panel.scroll, self.panel.max_scroll)
        self.assertTrue(any("NOTE 0:" in line for line in visible))
        self.assertTrue(any(target == "close" for _, target, _ in self.panel.hit_targets))

    def test_healing_preview_caps_recovery_and_includes_healer_bonus(self):
        supplied = deepcopy(SNAPSHOT)
        supplied["character"]["origin"] = "healers_apprentice"
        supplied["character"]["hp"] = 12
        self.panel.open("inventory", supplied)
        self.select_item("herb")
        self.assertEqual(self.panel._recovery_amount(self.panel._selected_item()), 11)
        supplied["character"]["hp"] = 25
        self.panel.open("inventory", supplied)
        self.select_item("herb")
        self.assertEqual(self.panel._recovery_amount(self.panel._selected_item()), 1)

    def test_background_preview_preserves_engine_identity_and_requires_a_choice(self):
        supplied = background_snapshot()
        before = deepcopy(supplied)
        self.panel.open("background", supplied)
        self.draw()
        self.assertEqual(self.click("origin", 2), (True, None))
        self.assertTrue(self.panel.active)
        self.draw()
        self.assertEqual(self.click("origin_action"), (True, {"action": "choose_origin", "origin_id": "healers_apprentice"}))
        self.assertEqual(supplied, before)
        self.assertEqual(self.panel.data, before)
        self.key(self.pg.K_LEFT)
        self.assertEqual(self.key(self.pg.K_RETURN), (True, {"action": "choose_origin", "origin_id": "north_road_scout"}))
        self.key(self.pg.K_1)
        self.assertEqual(self.key(self.pg.K_RETURN), (True, {"action": "choose_origin", "origin_id": "bree_wayfarer"}))

    def test_background_small_and_large_layouts_keep_choices_and_details_reachable(self):
        supplied = background_snapshot()
        supplied["origins"][0]["description"] += " The old roads remember. " * 80
        self.panel.open("background", supplied)
        for size, rect in (((760, 560), self.pg.Rect(23, 75, 714, 447)), ((1440, 900), self.pg.Rect(23, 75, 1394, 787))):
            screen = self.pg.Surface(size)
            self.panel.draw(screen, rect)
            cards = [(hit, value) for hit, target, value in self.panel.hit_targets if target == "origin"]
            self.assertEqual([value for _, value in cards], [0, 1, 2])
            self.assertTrue(all(self.panel.content_rect.contains(hit) for hit, _ in cards))
            action = next(hit for hit, target, _ in self.panel.hit_targets if target == "origin_action")
            self.assertTrue(rect.contains(action))
            self.assertGreater(self.panel.max_scroll, 0)
            self.key(self.pg.K_END)
            self.panel.draw(screen, rect)
            self.assertEqual(self.panel.scroll, self.panel.max_scroll)
            self.assertEqual(self.key(self.pg.K_RETURN), (True, {"action": "choose_origin", "origin_id": "bree_wayfarer"}))
            self.key(self.pg.K_HOME)
        self.assertEqual(self.key(self.pg.K_ESCAPE), (True, {"action": "close"}))

    def test_empty_backgrounds_do_not_return_an_invalid_character_selection(self):
        self.panel.open("background", {"origins": []})
        self.draw()
        self.assertEqual(self.key(self.pg.K_RETURN), (True, None))
        self.assertFalse(any(target == "origin_action" for _, target, _ in self.panel.hit_targets))

    def test_largest_text_keeps_inventory_and_background_buttons_readable_and_actionable(self):
        original_button = self.panel._button

        def readable_button(screen, rect, label, *args, **kwargs):
            rendered = self.panel.bold_font.render(label, False, (255, 255, 255))
            self.assertTrue(rect.contains(rendered.get_rect(center=rect.center)), label)
            return original_button(screen, rect, label, *args, **kwargs)

        self.panel._button = readable_button
        for size in ((760, 560), (1920, 1080)):
            screen = self.pg.Surface(size)
            rect = self.pg.Rect(23, 75, size[0] - 46, size[1] - 113)
            self.panel.open("inventory", SNAPSHOT)
            self.panel.selected = 1
            self.panel.draw(screen, rect, text_size="larger")
            action = next(hit for hit, target, _ in self.panel.hit_targets if target == "item_action")
            self.assertTrue(rect.contains(action))
            self.assertFalse(action.colliderect(self.panel.detail_body_rect))
            self.assertEqual(self.click("item_action"), (True, {"action": "equip", "item_id": "cleaver"}))
            self.panel.open("background", background_snapshot())
            self.panel.draw(screen, rect, text_size="larger")
            self.assertEqual(self.click("origin", 2), (True, None))
            self.panel.draw(screen, rect, text_size="larger")
            self.assertEqual(self.click("origin_action"), (True, {"action": "choose_origin", "origin_id": "healers_apprentice"}))

    def test_enlarged_background_prose_can_be_read_to_its_end_without_choosing(self):
        self.panel.open("background", background_snapshot())
        self.panel.selected = 2
        self.screen = self.pg.Surface((760, 560))
        self.rect = self.pg.Rect(23, 75, 714, 447)
        self.panel.draw(self.screen, self.rect, text_size="larger")
        self.assertGreater(self.panel.max_scroll, 0)
        self.key(self.pg.K_END)
        visible = []
        original_text = self.panel._text

        def record_visible(screen, text, x, y, *args, **kwargs):
            if self.panel.detail_body_rect.collidepoint(x, y):
                visible.append(str(text))
            return original_text(screen, text, x, y, *args, **kwargs)

        self.panel._text = record_visible
        self.panel.draw(self.screen, self.rect, text_size="larger")
        self.assertIn("Will strengthens Field Remedy.", " ".join(visible))
        self.assertEqual(self.panel.scroll, self.panel.max_scroll)
        self.assertTrue(self.panel.active)
        self.assertEqual(self.panel.selected, 2)

    def test_absent_feedback_does_not_show_a_none_message(self):
        supplied = deepcopy(SNAPSHOT)
        supplied["notice"] = None
        drawn = []
        original_text = self.panel._text

        def record_text(screen, text, *args, **kwargs):
            drawn.append(str(text))
            return original_text(screen, text, *args, **kwargs)

        self.panel._text = record_text
        for kind in ("inventory", "chronicle"):
            self.panel.open(kind, supplied)
            self.draw()
            self.assertNotIn("None", drawn)


if __name__ == "__main__":
    unittest.main()
