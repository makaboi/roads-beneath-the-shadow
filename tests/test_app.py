import random
import tempfile
import unittest
from pathlib import Path

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.combat import CombatConfig, CombatResult
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.profile import PlayerProfile, ProfileManager
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.ui import TerminalUI
from tests.helpers import EpisodePlayer, PartTwoPlayer, VictoryCombat


class CountingProfileManager(ProfileManager):
    def __init__(self, path: Path) -> None:
        super().__init__(path)
        self.record_calls = 0

    def record(self, state):
        self.record_calls += 1
        return super().record(state)


class GameFlowTests(unittest.TestCase):
    def test_main_menu_subtitle_reflects_an_active_part_two_journey(self) -> None:
        output: list[str] = []
        game = Game(
            TerminalUI(
                color=False,
                fast=True,
                input_fn=lambda _prompt: "7",
                output_fn=output.append,
            )
        )
        game.state = GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            chapter=2,
            scene="part2_descent",
        )

        game.run()

        transcript = "\n".join(output)
        self.assertIn("Part II — The Dead Road", transcript)
        self.assertNotIn("Part I — The Black Rider's Letter", transcript)

    def test_legacy_profile_recorded_flag_skips_profile_write(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            profile_path = Path(temporary) / "profile.json"
            existing_profile = PlayerProfile(
                completed_runs=1,
                endings={"fellowship": 1},
                origins_completed=["bree_wayfarer"],
                achievements=["part_one"],
                recorded_journeys=["existing-journey:part_1"],
            )
            ProfileManager(profile_path).save(existing_profile)
            before = profile_path.read_bytes()
            profile = CountingProfileManager(profile_path)
            self.assertEqual(profile.load(), existing_profile)
            game = Game(
                TerminalUI(color=False, fast=True, output_fn=lambda _: None),
                profile=profile,
            )
            game.state = GameState(
                Character.from_origin("Arin", ORIGINS[0]),
                scene="complete",
                ending="fellowship",
                flags={"profile_recorded": True},
            )

            self.assertEqual(game._record_completed_journey(), [])
            self.assertEqual(profile.record_calls, 0)
            self.assertEqual(profile_path.read_bytes(), before)

    def test_one_journey_records_part_one_and_part_two_once_at_application_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            player = PartTwoPlayer()
            profile = CountingProfileManager(Path(temporary) / "profile.json")
            game = Game(
                TerminalUI(
                    color=False,
                    fast=True,
                    input_fn=player.read,
                    output_fn=player.write,
                ),
                profile=profile,
            )
            game.combat = VictoryCombat()
            character = Character.from_origin("Arin", ORIGINS[0])
            character.hope = 3
            character.mara_trust = 3
            character.tobin_trust = 3
            character.add_item("star_key")
            game.state = GameState(
                character,
                chapter=1,
                scene="complete",
                ending="fellowship",
                flags={
                    "part_one_complete": True,
                    "defeated_ghorak": True,
                    "ned_survived": True,
                    "mara_chose_to_continue": True,
                    "tobin_chose_to_continue": True,
                },
                journey_id="task-5-chronicle",
            )

            game._record_completed_journey()
            game._begin_part_two()
            game._run_journey()
            recorded = profile.load()

            self.assertEqual(recorded.completed_runs, 2)
            self.assertEqual(
                recorded.recorded_journeys,
                ["task-5-chronicle:part_1", "task-5-chronicle:part_2"],
            )
            self.assertEqual(profile.record_calls, 2)

            game._show_ending()
            game._record_completed_journey()

            self.assertEqual(profile.load(), recorded)
            self.assertEqual(profile.record_calls, 2)

    def test_part_two_combat_callback_uses_replaced_game_combat(self) -> None:
        class ReplacementCombat:
            def __init__(self) -> None:
                self.calls = 0

            def run(self, _state, _enemies, _config):
                self.calls += 1
                return CombatResult.VICTORY

        game = Game(TerminalUI(color=False, fast=True, output_fn=lambda _: None))
        replacement = ReplacementCombat()
        game.combat = replacement
        state = GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            scene="part2_descent",
            chapter=2,
        )

        result = game.part_two.combat(state, [], CombatConfig())

        self.assertEqual(result, CombatResult.VICTORY)
        self.assertEqual(replacement.calls, 1)

    def test_part_one_dispatch_still_returns_from_story_menu(self) -> None:
        output: list[str] = []
        ui = TerminalUI(
            color=False,
            fast=True,
            input_fn=lambda _: "m",
            output_fn=output.append,
        )
        game = Game(ui)
        game.state = GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            scene="chapter1_decision",
        )

        game._run_journey()

        self.assertEqual(game.state.scene, "chapter1_decision")
        self.assertNotIn("Unknown scene", "\n".join(output))

    def test_part_one_ending_continues_into_handled_part_two_descent(self) -> None:
        answers = iter(("3", "m"))
        output: list[str] = []
        ui = TerminalUI(
            color=False,
            fast=True,
            input_fn=lambda _: next(answers),
            output_fn=output.append,
        )
        game = Game(ui)
        game.state = GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            scene="complete",
            ending="fellowship",
        )

        game._run_journey()

        transcript = "\n".join(output)
        self.assertEqual((game.state.chapter, game.state.scene), (2, "part2_descent"))
        self.assertIsNone(game.state.ending)
        self.assertIn("WHAT DO YOU CARRY DOWN?", transcript)
        self.assertNotIn("Unknown scene", transcript)

    def test_initial_new_journey_still_starts_without_discard_confirmation(self) -> None:
        answers = iter(["Arin", "1", "1", "1"])
        output: list[str] = []
        ui = TerminalUI(
            color=False,
            fast=True,
            input_fn=lambda _: next(answers),
            output_fn=output.append,
        )
        game = Game(ui, rng=random.Random(1))

        self.assertTrue(game._new_journey())
        self.assertEqual(game.state.character.name, "Arin")
        self.assertNotIn("unfinished journey", "\n".join(output))

    def test_new_journey_requires_confirmation_before_discarding_progress(self) -> None:
        original = GameState(Character.from_origin("Mira", ORIGINS[0]), scene="wayhouse")
        output: list[str] = []
        ui = TerminalUI(
            color=False,
            fast=True,
            input_fn=lambda _: "1",
            output_fn=output.append,
        )
        game = Game(ui, rng=random.Random(2))
        game.state = original

        self.assertFalse(game._new_journey())
        self.assertIs(game.state, original)
        self.assertIn("Your current journey has been kept.", output)

    def test_confirmed_discard_replaces_the_unfinished_journey(self) -> None:
        original = GameState(Character.from_origin("Mira", ORIGINS[0]), scene="wayhouse")
        answers = iter(["2", "Arin", "1", "1", "1"])
        ui = TerminalUI(
            color=False,
            fast=True,
            input_fn=lambda _: next(answers),
            output_fn=lambda _: None,
        )
        game = Game(ui, rng=random.Random(3))
        game.state = original

        self.assertTrue(game._new_journey())
        self.assertEqual(game.state.character.name, "Arin")
        self.assertNotEqual(game.state.journey_id, original.journey_id)

    def test_load_menu_handles_validation_failure_without_replacing_current_state(self) -> None:
        class InvalidLoad:
            @staticmethod
            def all_slots():
                return [
                    {"name": "Spoof", "chapter": 1, "ending": None},
                    None,
                    None,
                ]

            @staticmethod
            def slot_metadata(_slot):
                return {"name": "Spoof", "chapter": 1, "ending": None}

            @staticmethod
            def load(_slot):
                raise ValueError("scene must not contain control characters")

        original = GameState(Character.from_origin("Mira", ORIGINS[0]), scene="wayhouse")
        output: list[str] = []
        ui = TerminalUI(
            color=False,
            fast=True,
            input_fn=lambda _: "1",
            output_fn=output.append,
        )
        game = Game(ui, saves=InvalidLoad(), rng=random.Random(4))
        game.state = original

        self.assertFalse(game._load_menu())
        self.assertIs(game.state, original)
        self.assertIn(
            "Could not load the journey: scene must not contain control characters",
            output,
        )

    def test_full_part_one_contains_required_episode_beats(self) -> None:
        player = EpisodePlayer(opening_choice=1)
        ui = TerminalUI(color=False, fast=True, input_fn=player.read, output_fn=player.write)
        with tempfile.TemporaryDirectory() as temporary:
            game = Game(ui, saves=SaveManager(Path(temporary)), rng=random.Random(12))
            combat = VictoryCombat()
            game.combat = combat
            game.run()

        state = game.state
        transcript = "\n".join(player.output)
        self.assertTrue(state.flags["part_one_complete"])
        self.assertTrue(state.flags["defeated_ghorak"])
        self.assertTrue(state.flags["ned_survived"])
        self.assertIn("Find missing watchman Ned Barley in the Midgewater fringe", state.completed_quests)
        self.assertEqual(len(combat.encounters), 3)
        self.assertGreaterEqual(state.play_minutes, 55)
        self.assertGreaterEqual(player.prompt_count, 20)
        self.assertTrue(state.flags["part_two_hidden_route_known"])
        self.assertIn(state.ending, {"hidden_road", "shadow_claim"})
        for required in (
            "PART I — THE BLACK RIDER'S LETTER",
            '"The silver star. Take its bearer alive."',
            "BREE BEFORE MIDNIGHT",
            "THE THIRD STONE",
            "THE LOST WHISTLE",
            "THE FINAL BATTLE",
            "THE EIGHTH HORN",
            "THE ROAD YOU MADE",
            "Tobin and Ned:",
            "These consequences are carried into Part II.",
            "PART I COMPLETE",
        ):
            self.assertIn(required, transcript)

    def test_real_combat_route_completes_episode(self) -> None:
        player = EpisodePlayer(opening_choice=1, origin_choice=1, real_combat=True)
        ui = TerminalUI(color=False, fast=True, input_fn=player.read, output_fn=player.write)
        with tempfile.TemporaryDirectory() as temporary:
            game = Game(ui, saves=SaveManager(Path(temporary)), rng=random.Random(8))
            game.run()

        self.assertTrue(game.state.flags["part_one_complete"])
        self.assertTrue(game.state.character.alive)
        self.assertIn(game.state.ending, {"hidden_road", "shadow_claim"})

    def test_existing_ending_menu_numbers_remain_stable(self) -> None:
        ui = TerminalUI(color=False, fast=True, input_fn=lambda _: "2", output_fn=lambda _: None)
        game = Game(ui)
        game.state = GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            scene="complete",
            ending="fellowship",
        )

        game._show_ending()

        self.assertEqual(game.state.scene, "complete")
        self.assertEqual(game.state.ending, "fellowship")

    def test_full_route_announces_new_visual_story_beats_to_screen_readers(self) -> None:
        player = EpisodePlayer(opening_choice=1)
        ui = TerminalUI(
            color=False,
            fast=True,
            screen_reader=True,
            input_fn=player.read,
            output_fn=player.write,
        )
        with tempfile.TemporaryDirectory() as temporary:
            game = Game(ui, saves=SaveManager(Path(temporary)), rng=random.Random(12))
            game.combat = VictoryCombat()
            game.run()

        transcript = "\n".join(player.output)
        for scene in (
            "A broken watch-lantern lies beside huge wolf tracks in the rain.",
            "Bree's last lamps recede behind a narrow road into the wild.",
            "Ned hangs in a black-rope snare above a drowned watch post.",
            "The completed eight-pointed star-key wakes with silver light.",
        ):
            self.assertIn(f"[Scene: {scene}]", transcript)

    def test_wayhouse_shrine_announces_the_crowned_reflection(self) -> None:
        answers = iter(["1", "1", "1"])
        output: list[str] = []
        ui = TerminalUI(
            color=False,
            fast=True,
            screen_reader=True,
            input_fn=lambda _: next(answers),
            output_fn=output.append,
        )
        game = Game(ui, rng=random.Random(4))
        game.state = GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            scene="wayhouse",
            flags={"wayhouse_opened": True},
            visited=["wayhouse_entry", "wayhouse_armory", "wayhouse_archive"],
        )

        self.assertTrue(game._wayhouse())
        self.assertIn(
            "[Scene: A stone chair faces a polished wall where a crowned reflection raises its hand.]",
            output,
        )


if __name__ == "__main__":
    unittest.main()
