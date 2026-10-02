"""Read-only maps and chronicles expose player-facing information."""

import unittest
from copy import deepcopy

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.player_view import chronicle_snapshot, player_snapshot, route_snapshot
from roads_beneath_shadow.profile import ACHIEVEMENTS, PlayerProfile
from roads_beneath_shadow.ui import TerminalUI


class ReadOnlyPanelUI(TerminalUI):
    def __init__(self, story_actions=()):
        self.panels = []
        self.output = []
        self.actions = iter(story_actions)
        self.pauses = 0
        super().__init__(color=False, fast=True, output_fn=self.output.append)

    def show_panel(self, kind, data):
        self.panels.append((kind, deepcopy(data)))
        return {"action": "close"}

    def choose_story(self, heading, options):
        return next(self.actions)

    def pause(self, message=""):
        self.pauses += 1


class PlayerViewTests(unittest.TestCase):
    @staticmethod
    def state(scene="part2_vigil"):
        return GameState(Character.from_origin("Mira", ORIGINS[1]), scene=scene, chapter=2 if scene.startswith("part2_") else 1)

    def test_map_shows_explored_places_and_current_location_without_future_spoilers(self):
        state = self.state()
        state.visited = ["messenger_room", "stable_yard", "wayhouse_armory"]
        state.flags.update({"part2_cipher_archive": True, "part_two_hidden_route_known": True})
        before = state.to_dict()
        snapshot = route_snapshot(state)
        names = [entry["name"] for entry in snapshot["route"]]
        self.assertEqual(names, ["Edrin's Room", "The Pony's Stable Yard", "The Drowned Armory", "The Cipher Archive", "The Last Lantern"])
        self.assertEqual(sum(entry["current"] for entry in snapshot["route"]), 1)
        self.assertEqual(snapshot["route"][-1], {"name": "The Last Lantern", "visited": False, "current": True})
        self.assertNotIn("Fornost", str(snapshot))
        self.assertNotIn("Erased Statue", str(snapshot))
        self.assertNotIn("Last Seal", str(snapshot))
        self.assertFalse(any("_" in name for name in names))
        snapshot["route"][0]["name"] = "Changed by caller"
        self.assertEqual(state.to_dict(), before)

    def test_map_handles_legacy_visit_labels_and_deduplicates_current_place(self):
        state = self.state("north_gate")
        state.visited = ["Bree", "north_gate", "north_gate", "old_internal_scene_id"]
        route = route_snapshot(state)["route"]
        self.assertEqual([entry["name"] for entry in route], ["Bree", "Bree's North Gate", "A remembered stop"])
        self.assertEqual(sum(entry["current"] for entry in route), 1)
        self.assertEqual(route[1], {"name": "Bree's North Gate", "visited": True, "current": True})
        self.assertNotIn("old_internal_scene_id", str(route))

    def test_player_panel_visit_labels_do_not_expose_internal_room_ids(self):
        state = self.state("wayhouse")
        state.visited = ["pony_kitchen", "wayhouse_archive"]
        snapshot = player_snapshot(state)
        self.assertEqual(snapshot["visited"], ["The Pony's Kitchen", "The Wayhouse Archive"])
        self.assertEqual(state.visited, ["pony_kitchen", "wayhouse_archive"])

    def test_chronicle_snapshot_contains_every_achievement_and_only_witnessed_endings(self):
        profile = PlayerProfile(
            completed_runs=4,
            origins_completed=[ORIGINS[0].origin_id, ORIGINS[2].origin_id],
            endings={"fellowship": 3, "living_road": 1},
            achievements=["part_one", "part_two"],
        )
        before = deepcopy(profile)
        snapshot = chronicle_snapshot(profile)
        self.assertEqual(snapshot["completed_runs"], 4)
        self.assertEqual(snapshot["origins"], [ORIGINS[0].name, ORIGINS[2].name])
        self.assertEqual(snapshot["endings"], [{"name": "Beneath The Shadow", "count": 3}, {"name": "The Living Road", "count": 1}])
        self.assertEqual([entry["id"] for entry in snapshot["achievements"]], list(ACHIEVEMENTS))
        self.assertEqual({entry["id"] for entry in snapshot["achievements"] if entry["earned"]}, {"part_one", "part_two"})
        snapshot["origins"].clear()
        snapshot["achievements"][0]["earned"] = False
        self.assertEqual(profile, before)

    def test_map_utility_returns_to_same_story_choice_without_changing_journey(self):
        ui = ReadOnlyPanelUI(("r", 2))
        game = Game(ui)
        game.state = self.state("north_gate")
        before = game.state.to_dict()
        self.assertEqual(game._story_choice("A CHOICE", ("Stay", "Continue")), 2)
        self.assertEqual(ui.panels[0][0], "map")
        self.assertEqual(game.state.to_dict(), before)

    def test_graphical_chronicle_uses_a_scrollable_panel_without_live_profile_references(self):
        profile = PlayerProfile(completed_runs=1, origins_completed=[ORIGINS[1].origin_id], achievements=["part_one"])

        class ProfileReader:
            def load(self):
                return profile

        ui = ReadOnlyPanelUI()
        Game(ui, profile=ProfileReader())._show_chronicle()
        self.assertEqual(ui.panels[0][0], "chronicle")
        self.assertEqual(ui.panels[0][1]["completed_runs"], 1)
        self.assertEqual(len(ui.panels[0][1]["achievements"]), len(ACHIEVEMENTS))
        self.assertEqual(ui.pauses, 0)
        self.assertEqual(profile.achievements, ["part_one"])

    def test_graphical_help_explains_world_pages_panels_and_saving(self):
        ui = ReadOnlyPanelUI()
        Game(ui)._how_to_play()
        self.assertEqual(ui.panels[0][0], "information")
        instructions = " ".join(section["text"] for section in ui.panels[0][1]["sections"])
        for control in ("WASD", "Press E", "click", "numbered choices", "Space or Enter", "Tab", "F5", "R shows the road map"):
            self.assertIn(control, instructions)
        self.assertEqual(ui.pauses, 0)


if __name__ == "__main__":
    unittest.main()
