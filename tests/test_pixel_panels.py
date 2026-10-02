"""Modal snapshots and SDL interaction must preserve the story's authority."""

import importlib.util
import os
import unittest
from copy import deepcopy

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from roads_beneath_shadow.pixel_panels import PanelView, _wrap
from roads_beneath_shadow.player_view import chronicle_snapshot
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

    def test_long_description_scrolling_keeps_offscreen_actions_unclickable(self):
        supplied = deepcopy(SNAPSHOT)
        supplied["items"][2]["description"] = "Old roads remember every footstep. " * 100
        self.panel.open("inventory", supplied)
        self.select_item("cleaver")
        self.assertGreater(self.panel.max_detail_scroll, 0)
        self.assertFalse(any(target == "item_action" for _, target, _ in self.panel.hit_targets))
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
            self.draw()
            self.assertGreater(self.panel.max_scroll, 0, kind)
            self.key(self.pg.K_END)
            self.draw()
            self.assertEqual(self.panel.scroll, self.panel.max_scroll)
            self.assertEqual(self.key(self.pg.K_RETURN), (True, {"action": "close"}))
            self.assertFalse(self.panel.active)

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
        self.assertIn("Completed journeys: 5", visible)
        visible.clear()
        self.key(self.pg.K_END)
        self.draw()
        self.assertEqual(self.panel.scroll, self.panel.max_scroll)
        self.assertIn("No Name for the Shadow", visible)
        self.assertIn("UNDISCOVERED", visible)
        self.assertNotIn("Completed journeys: 5", visible)
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


if __name__ == "__main__":
    unittest.main()
