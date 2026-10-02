import tempfile
import unittest
from pathlib import Path

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.profile import PlayerProfile, ProfileManager
from roads_beneath_shadow.ui import TerminalUI


class PlayerProfileTests(unittest.TestCase):
    def test_completed_run_unlocks_matching_achievements(self) -> None:
        state = GameState(Character.from_origin("Arin", ORIGINS[0]))
        state.ending = "fellowship"
        state.character.hope = 5
        state.character.corruption = 1
        state.flags.update(
            {
                "ned_survived": True,
                "mara_chose_to_continue": True,
                "tobin_chose_to_continue": True,
            }
        )
        state.journal = [f"Clue {index}" for index in range(12)]

        profile = PlayerProfile()
        unlocked = profile.record(state)

        self.assertIn("part_one", unlocked)
        self.assertIn("none_left_behind", unlocked)
        self.assertIn("unbroken_hope", unlocked)
        self.assertIn("road_scholar", unlocked)
        self.assertEqual(profile.endings, {"fellowship": 1})

    def test_profile_manager_round_trip_does_not_duplicate_a_completed_journey(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = ProfileManager(Path(temporary) / "profile.json")
            state = GameState(Character.from_origin("Arin", ORIGINS[1]))
            state.ending = "shadow_claim"
            state.character.corruption = 4

            first = manager.record(state)
            second = manager.record(state)
            loaded = manager.load()

            self.assertIn("shadow_touched", first)
            self.assertNotIn("shadow_touched", second)
            self.assertEqual(loaded.completed_runs, 1)
            self.assertEqual(loaded.endings["shadow_claim"], 1)

    def test_same_journey_records_one_ending_per_episode(self) -> None:
        profile = PlayerProfile()
        state = GameState(Character.from_origin("Arin", ORIGINS[0]), journey_id="road-7")
        state.scene = "complete"
        state.ending = "fellowship"
        profile.record(state)

        state.chapter = 2
        state.ending = "living_road"
        profile.record(state)
        profile.record(state)

        self.assertEqual(profile.completed_runs, 2)
        self.assertEqual(profile.recorded_journeys, ["road-7:part_1", "road-7:part_2"])

    def test_old_unqualified_record_still_deduplicates_part_one(self) -> None:
        profile = PlayerProfile(recorded_journeys=["legacy-road"], completed_runs=1)
        state = GameState(Character.from_origin("Arin", ORIGINS[0]), journey_id="legacy-road")
        state.scene = "complete"
        state.ending = "fellowship"

        self.assertEqual(profile.record(state), [])
        self.assertEqual(profile.completed_runs, 1)

    def test_maximum_length_episode_record_survives_profile_loading(self) -> None:
        profile = PlayerProfile()
        state = GameState(Character.from_origin("Arin", ORIGINS[0]), journey_id="r" * 128)
        state.chapter = 2
        state.ending = "living_road"

        profile.record(state)
        loaded = PlayerProfile.from_dict({"recorded_journeys": profile.recorded_journeys})

        self.assertEqual(loaded.recorded_journeys, [f"{'r' * 128}:part_2"])

    def test_incomplete_journey_cannot_be_recorded(self) -> None:
        state = GameState(Character.from_origin("Arin", ORIGINS[2]))
        with self.assertRaises(ValueError):
            PlayerProfile().record(state)

    def test_damaged_or_hostile_profile_labels_are_ignored(self) -> None:
        profile = PlayerProfile.from_dict(
            {
                "completed_runs": 2,
                "endings": {"fellowship": 1, "\x1b[31mspoof": 99},
                "origins_completed": ["bree_wayfarer", "invented_origin"],
                "recorded_journeys": ["safe-id", "bad\nline", "x" * 200],
            }
        )

        self.assertEqual(profile.endings, {"fellowship": 1})
        self.assertEqual(profile.origins_completed, ["bree_wayfarer"])
        self.assertEqual(profile.recorded_journeys, ["safe-id"])

    def test_ending_screen_records_once_and_chronicle_reads_the_profile(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = ProfileManager(Path(temporary) / "profile.json")
            output: list[str] = []
            ui = TerminalUI(
                color=False,
                fast=True,
                input_fn=lambda _: "2",
                output_fn=output.append,
            )
            game = Game(ui, profile=manager)
            game.state = GameState(Character.from_origin("Arin", ORIGINS[0]))
            game.state.ending = "fellowship"
            game.state.flags.update(
                {"defeated_ghorak": True, "ned_survived": True, "part_two_hidden_route_known": False}
            )

            game._show_ending()
            game._show_ending()
            game._show_chronicle()

            loaded = manager.load()
            transcript = "\n".join(output)
            self.assertEqual(loaded.completed_runs, 1)
            self.assertIn("The Road Opens", transcript)
        self.assertIn("Completed episodes: 1", transcript)

    def test_part_two_living_road_unlocks_only_part_two_achievements(self) -> None:
        state = GameState(Character.from_origin("Arin", ORIGINS[0]))
        state.chapter = 2
        state.scene = "complete"
        state.ending = "living_road"
        state.character.hope = 8
        state.character.corruption = 0
        state.flags.update(
            {
                "part2_testimony_first": True,
                "part2_testimony_second": True,
                "part2_testimony_third": True,
                "part2_prisoners_rescued": True,
                "part_two_mara_present": True,
                "part_two_tobin_present": False,
                "part2_star_rejected": True,
            }
        )

        unlocked = PlayerProfile().record(state)

        self.assertEqual(
            unlocked,
            ["part_two", "names_remembered", "none_forsaken", "no_name_for_shadow"],
        )
        self.assertNotIn("part_one", unlocked)
        self.assertNotIn("unbroken_hope", unlocked)

    def test_no_name_for_shadow_rejects_every_explicit_star_power_path(self) -> None:
        forbidden = (
            "accepted_star_power",
            "used_star_in_final",
            "part2_star_commanded",
            "part2_star_guided_descent",
            "part2_spoke_hidden_name",
            "part2_star_read_memory",
            "part2_star_broke_chain",
            "part2_star_bargain",
            "part2_descent_mark_bargain",
        )
        for flag in forbidden:
            with self.subTest(flag=flag):
                state = GameState(Character.from_origin("Arin", ORIGINS[0]))
                state.chapter = 2
                state.scene = "complete"
                state.ending = "living_road"
                state.flags.update({"part2_star_rejected": True, flag: True})

                unlocked = PlayerProfile().record(state)

                self.assertIn("part_two", unlocked)
                self.assertNotIn("no_name_for_shadow", unlocked)

    def test_part_two_endings_do_not_count_toward_fates_witnessed(self) -> None:
        profile = PlayerProfile(
            endings={"fellowship": 1, "hidden_road": 1, "living_road": 1},
            completed_runs=3,
        )
        state = GameState(Character.from_origin("Arin", ORIGINS[0]))
        state.ending = "keeper_of_secrets"

        unlocked = profile.record(state)

        self.assertNotIn("fates_witnessed", unlocked)

    def test_zero_count_part_one_ending_does_not_count_as_witnessed(self) -> None:
        profile = PlayerProfile(
            endings={
                "fellowship": 1,
                "hidden_road": 1,
                "keeper_of_secrets": 1,
                "shadow_claim": 0,
                "living_road": 1,
            },
            completed_runs=4,
        )
        state = GameState(Character.from_origin("Arin", ORIGINS[0]))
        state.ending = "fellowship"

        unlocked = profile.record(state)

        self.assertNotIn("fates_witnessed", unlocked)


if __name__ == "__main__":
    unittest.main()
