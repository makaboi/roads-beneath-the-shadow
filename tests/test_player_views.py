"""Read-only maps and chronicles expose player-facing information."""

import unittest
from copy import deepcopy

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.content import ORIGINS, QUEST_NAMES_LOST, QUEST_REACH_CALENOR
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.player_view import background_snapshot, chronicle_snapshot, player_snapshot, route_snapshot
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

    def test_hall_rooms_follow_their_stop_without_reordering_recorded_inspections(self):
        state = self.state("part2_last_seal")
        state.visited = ["complete", "part2_hall", "part2_echo_bridge", "part2_teren", "part2_erased_statue", "part2_cipher_archive", "part2_last_seal"]
        state.flags.update({"part2_cipher_archive": True, "part2_erased_statue": True})
        before = state.to_dict()
        names = [place["name"] for place in route_snapshot(state)["route"]]
        self.assertEqual(names, ["The Hall of Eight", "The Erased Statue", "The Cipher Archive", "Echo Bridge", "The Warden Refuge", "The Last Seal"])
        self.assertNotIn("The Road Ahead", names)
        self.assertEqual(state.to_dict(), before)
        state.scene = "complete"
        route = route_snapshot(state)["route"]
        self.assertEqual(route[-1], {"name": "The Road Ahead", "visited": True, "current": True})

    def test_legacy_earned_hall_rooms_stay_near_the_hall_and_hidden_rooms_stay_hidden(self):
        state = self.state("part2_vigil")
        state.visited = ["part2_hall", "part2_echo_bridge", "part2_teren"]
        state.flags["part2_cipher_archive"] = True
        names = [place["name"] for place in route_snapshot(state)["route"]]
        self.assertEqual(names[:3], ["The Hall of Eight", "The Cipher Archive", "Echo Bridge"])
        self.assertNotIn("The Erased Statue", names)

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
        for control in ("WASD", "press E", "click", "numbered", "Space or Enter", "Tab", "F5", "R shows the road map"):
            self.assertIn(control.casefold(), instructions.casefold())
        self.assertEqual(ui.pauses, 0)

    def test_live_decision_copy_preserves_option_order_without_exposing_future_choices(self):
        state = self.state("bree_exploration")
        decision = {"heading": "WHERE WILL YOU INVESTIGATE?", "options": ["Search the stable yard", "Go to the north gate"]}
        for snapshot in (player_snapshot(state, decision=decision), route_snapshot(state, decision=decision)):
            self.assertEqual(snapshot["decision"], decision)
            decision["options"].append("A later edit")
            self.assertNotIn("A later edit", snapshot["decision"]["options"])
            decision["options"].pop()
            self.assertNotIn("Fornost", str(snapshot))
            self.assertNotIn("Last Seal", str(snapshot))

    def test_journal_guidance_uses_only_active_objectives_and_recorded_evidence(self):
        state = self.state("part2_hall_exploration")
        state.quests = [QUEST_NAMES_LOST]
        state.journal = ["A Warden's first testimony names the road home.", "Mara remembers a fireside in Bree."]
        state.flags["part2_testimony_first"] = True
        before = state.to_dict()
        snapshot = player_snapshot(state)
        detail = snapshot["quest_details"][0]
        self.assertEqual(detail["title"], QUEST_NAMES_LOST)
        self.assertEqual(detail["progress"], "1 of 3 testimonies recovered")
        self.assertEqual(detail["related_clues"], [state.journal[0]])
        self.assertNotIn("Calenor's Prison", str(detail))
        self.assertNotIn("Last Seal", str(detail))
        detail["related_clues"].clear()
        self.assertEqual(state.to_dict(), before)

    def test_healer_supply_capacity_and_rescued_companion_are_grounded_in_state(self):
        state = GameState(Character.from_origin("Mira", ORIGINS[2]), scene="part2_vigil", chapter=2)
        state.character.hp -= 12
        snapshot = player_snapshot(state)
        herb = next(item for item in snapshot["items"] if item["id"] == "healing_herb")
        self.assertEqual(herb["healing_effective"], herb["healing"] + 2)
        self.assertNotIn("Calenor", [person["name"] for person in snapshot["companions"]])
        state.completed_quests.append(QUEST_REACH_CALENOR)
        snapshot = player_snapshot(state)
        calenor = next(person for person in snapshot["companions"] if person["name"] == "Calenor")
        self.assertTrue(calenor["present"])
        self.assertNotIn("trust", calenor)
        state.flags["part2_calenor_remained"] = True
        calenor = next(person for person in player_snapshot(state)["companions"] if person["name"] == "Calenor")
        self.assertFalse(calenor["present"])

    def test_chronicle_counts_episode_completions_separately(self):
        snapshot = chronicle_snapshot(PlayerProfile(completed_runs=4, endings={"fellowship": 2, "living_road": 1, "road_in_ruin": 1}))
        self.assertEqual(snapshot["part_one_completions"], 2)
        self.assertEqual(snapshot["part_two_completions"], 2)

    def test_background_cards_expose_all_engine_origins_and_count_starting_supplies(self):
        snapshot = background_snapshot()
        self.assertEqual([entry["id"] for entry in snapshot["origins"]], [origin.origin_id for origin in ORIGINS])
        for entry, origin in zip(snapshot["origins"], ORIGINS):
            self.assertEqual(entry["max_hp"], Character.from_origin("Arin", origin).max_hp)
            self.assertEqual(entry["ability_name"], origin.ability_name)
            self.assertEqual(entry["ability_description"], origin.ability_description)
            self.assertFalse(any("_" in item for item in entry["starting_items"]))
        self.assertIn("Healing Herb ×2", snapshot["origins"][2]["starting_items"])
        snapshot["origins"][0]["starting_items"].clear()
        self.assertTrue(background_snapshot()["origins"][0]["starting_items"])


if __name__ == "__main__":
    unittest.main()
