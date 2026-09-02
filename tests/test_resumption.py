import random
import tempfile
import unittest
from pathlib import Path

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.ui import TerminalUI
from tests.helpers import PartTwoPlayer, VictoryCombat


class ResumptionTests(unittest.TestCase):
    def test_aftermath_reward_is_idempotent_across_save_load(self) -> None:
        output: list[str] = []
        with tempfile.TemporaryDirectory() as temporary:
            saves = SaveManager(Path(temporary))
            state = GameState(Character.from_origin("Arin", ORIGINS[0]), scene="aftermath")
            state.character.hp = 5
            first_ui = TerminalUI(color=False, fast=True, input_fn=lambda _: "m", output_fn=output.append)
            first = Game(first_ui, saves=saves, rng=random.Random(1))
            first.state = state

            self.assertFalse(first._aftermath())
            hp_after_setup = state.character.hp
            self.assertTrue(state.flags["aftermath_setup"])
            saves.save(1, state)

            resumed_state = saves.load(1)
            second_ui = TerminalUI(color=False, fast=True, input_fn=lambda _: "m", output_fn=output.append)
            second = Game(second_ui, saves=saves, rng=random.Random(1))
            second.state = resumed_state

            self.assertFalse(second._aftermath())
            self.assertEqual(resumed_state.character.hp, hp_after_setup)
            self.assertEqual(resumed_state.character.inventory["orc_cleaver"], 1)

    def test_cliffhanger_consequences_are_idempotent_across_reentry(self) -> None:
        output: list[str] = []
        state = GameState(Character.from_origin("Arin", ORIGINS[0]), scene="cliffhanger")
        state.character.hope = 3
        state.character.mara_trust = 2
        state.character.tobin_trust = 2
        state.flags.update({"defeated_ghorak": True, "ned_survived": True})
        game = Game(
            TerminalUI(color=False, fast=True, input_fn=lambda _: "2", output_fn=output.append),
            rng=random.Random(2),
        )
        game.state = state

        game._cliffhanger()
        minutes_after_first_resolution = state.play_minutes
        journal_after_first_resolution = list(state.journal)
        quests_after_first_resolution = list(state.quests)
        ending_after_first_resolution = state.ending

        game._cliffhanger()

        self.assertEqual(state.play_minutes, minutes_after_first_resolution)
        self.assertEqual(state.journal, journal_after_first_resolution)
        self.assertEqual(state.quests, quests_after_first_resolution)
        self.assertEqual(state.ending, ending_after_first_resolution)
        self.assertTrue(state.flags["cliffhanger_resolved"])

    def test_part_two_replay_from_echo_bridge_matches_uninterrupted_state(self) -> None:
        def assert_checkpoint(state: GameState) -> None:
            self.assertTrue(state.flags["part2_testimony_first"])

        self._assert_part_two_replay("part2_echo_bridge", assert_checkpoint)

    def test_part_two_replay_from_house_under_ash_matches_uninterrupted_state(self) -> None:
        def assert_checkpoint(state: GameState) -> None:
            self.assertTrue(state.flags["part2_testimony_second"])
            self.assertGreater(state.character.hope, 0)

        self._assert_part_two_replay("part2_house_under_ash", assert_checkpoint)

    def test_part_two_replay_from_seal_choice_matches_uninterrupted_state(self) -> None:
        def assert_checkpoint(state: GameState) -> None:
            self.assertTrue(state.flags["part2_testimony_third"])

        self._assert_part_two_replay("part2_seal_choice", assert_checkpoint)

    def _assert_part_two_replay(self, checkpoint, assert_checkpoint) -> None:
        journey_id = f"task-5-{checkpoint}"
        control_player = PartTwoPlayer()
        control = self._part_two_game(control_player, journey_id)
        control._run_journey()

        checkpoint_player = PartTwoPlayer()
        checkpoint_game = self._part_two_game(checkpoint_player, journey_id)
        for _scene in range(16):
            if checkpoint_game.state.scene == checkpoint:
                break
            self.assertTrue(checkpoint_game.part_two.run_scene(checkpoint_game.state))
        self.assertEqual(checkpoint_game.state.scene, checkpoint)
        assert_checkpoint(checkpoint_game.state)

        with tempfile.TemporaryDirectory() as temporary:
            save_root = Path(temporary)
            writer_saves = SaveManager(save_root)
            writer_saves.save(1, checkpoint_game.state)
            resumed_saves = SaveManager(save_root)
            loaded = resumed_saves.load(1)
            resumed_player = PartTwoPlayer()
            resumed = Game(
                TerminalUI(
                    color=False,
                    fast=True,
                    input_fn=resumed_player.read,
                    output_fn=resumed_player.write,
                ),
                saves=resumed_saves,
                rng=random.Random(5),
            )
            self.assertIsNot(resumed.saves, writer_saves)
            resumed.combat = VictoryCombat()
            resumed.state = loaded
            resumed._run_journey()

        self.assertEqual(resumed.state.to_dict(), control.state.to_dict())

    @staticmethod
    def _part_two_game(player: PartTwoPlayer, journey_id: str) -> Game:
        game = Game(
            TerminalUI(
                color=False,
                fast=True,
                input_fn=player.read,
                output_fn=player.write,
            ),
            rng=random.Random(5),
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
            play_minutes=60,
            journey_id=journey_id,
        )
        game._begin_part_two()
        return game


if __name__ == "__main__":
    unittest.main()
