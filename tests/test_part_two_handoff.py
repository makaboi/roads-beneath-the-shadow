import json
import random
import tempfile
import unittest
from pathlib import Path

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.part_two import begin_part_two
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.ui import TerminalUI


class PartTwoHandoffTests(unittest.TestCase):
    @staticmethod
    def _load_fixture(root: Path, state: dict) -> GameState:
        (root / "slot_1.json").write_text(
            json.dumps({"saved_at": "then", "state": state}), encoding="utf-8"
        )
        return SaveManager(root).load(1)

    def test_part_one_ending_menu_can_begin_part_two(self) -> None:
        answers = iter(("3",))
        ui = TerminalUI(
            color=False,
            fast=True,
            input_fn=lambda _: next(answers),
            output_fn=lambda _: None,
        )
        game = Game(ui, rng=random.Random(4))
        state = GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            scene="complete",
            ending="hidden_road",
            flags={"learned_dead_road_map": True, "found_ranger_cipher": True},
        )
        game.state = state

        game._show_ending()

        self.assertEqual(state.scene, "part2_descent")
        self.assertTrue(state.flags["part_two_hidden_route_known"])

    def test_each_part_one_ending_becomes_an_active_chapter_two_state(self) -> None:
        for ending in ("fellowship", "hidden_road", "keeper_of_secrets", "shadow_claim"):
            with self.subTest(ending=ending):
                character = Character.from_origin("Arin", ORIGINS[0])
                character.hp = 1
                character.focus = 0
                character.add_item("star_key")
                state = GameState(
                    character,
                    scene="complete",
                    ending=ending,
                    quests=[
                        "Find Calenor's mark at Bree's north gate",
                        "Find the Dead Road before Calenor is taken there",
                        "Descend the Dead Road and reach Calenor",
                    ],
                )

                begin_part_two(state)

                self.assertEqual(state.chapter, 2)
                self.assertEqual(state.scene, "part2_descent")
                self.assertIsNone(state.ending)
                self.assertTrue(state.flags["part_two_started"])
                self.assertNotIn("star_key", state.character.inventory)
                self.assertEqual(state.character.inventory["calenor_broken_sword"], 1)
                self.assertGreaterEqual(state.character.hp, state.character.max_hp // 2)
                self.assertEqual(state.character.focus, state.character.max_focus)
                self.assertIn("Learn why the silver star is the last seal", state.quests)
                self.assertIn("Find Calenor's mark at Bree's north gate", state.completed_quests)
                self.assertIn("Find the Dead Road before Calenor is taken there", state.completed_quests)

    def test_handoff_is_idempotent(self) -> None:
        state = GameState(
            Character.from_origin("Arin", ORIGINS[1]),
            scene="complete",
            ending="fellowship",
        )
        begin_part_two(state)
        snapshot = state.to_dict()

        begin_part_two(state)

        self.assertEqual(state.to_dict(), snapshot)

    def test_active_part_two_state_round_trips_through_version_two_save(self) -> None:
        state = GameState(
            Character.from_origin("Arin", ORIGINS[2]),
            scene="complete",
            ending="keeper_of_secrets",
        )
        begin_part_two(state)
        with tempfile.TemporaryDirectory() as temporary:
            saves = SaveManager(Path(temporary))
            saves.save(1, state)
            loaded = saves.load(1)

        self.assertEqual(loaded.to_dict(), state.to_dict())
        self.assertEqual(loaded.save_version, 2)

    def test_game_handoff_rebuilds_companion_presence_from_version_one_save(self) -> None:
        state = GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            scene="complete",
            ending="fellowship",
            flags={"mara_continues_warily": True, "tobin_carries_neds_watch": True},
        ).to_dict()
        state["save_version"] = 1
        state["character"].pop("tobin_trust")
        state.pop("journey_id")
        state.pop("visited")
        state.pop("completed_quests")
        state.pop("play_minutes")

        with tempfile.TemporaryDirectory() as temporary:
            loaded = self._load_fixture(Path(temporary), state)
            game = Game(TerminalUI(color=False, fast=True, output_fn=lambda _: None))
            game.state = loaded
            game._begin_part_two()

        self.assertTrue(loaded.flags["part_two_mara_present"])
        self.assertTrue(loaded.flags["part_two_tobin_present"])

    def test_game_handoff_uses_legacy_presence_fallbacks_for_version_two_save(self) -> None:
        character = Character.from_origin("Arin", ORIGINS[0])
        character.tobin_trust = 3
        state = GameState(
            character,
            scene="complete",
            ending="fellowship",
            flags={"ned_survived": True},
        ).to_dict()

        with tempfile.TemporaryDirectory() as temporary:
            loaded = self._load_fixture(Path(temporary), state)
            game = Game(TerminalUI(color=False, fast=True, output_fn=lambda _: None))
            game.state = loaded
            game._begin_part_two()

        self.assertTrue(loaded.flags["part_two_mara_present"])
        self.assertTrue(loaded.flags["part_two_tobin_present"])

    def test_game_handoff_keeps_mara_present_with_false_legacy_outcome_flags(self) -> None:
        state = GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            scene="complete",
            ending="fellowship",
            flags={"mara_chose_to_continue": False},
        ).to_dict()

        with tempfile.TemporaryDirectory() as temporary:
            loaded = self._load_fixture(Path(temporary), state)
            game = Game(TerminalUI(color=False, fast=True, output_fn=lambda _: None))
            game.state = loaded
            game._begin_part_two()

        self.assertTrue(loaded.flags["part_two_mara_present"])

    def test_game_handoff_preserves_explicit_tobin_absence(self) -> None:
        character = Character.from_origin("Arin", ORIGINS[0])
        character.tobin_trust = 3
        state = GameState(
            character,
            scene="complete",
            ending="fellowship",
            flags={"ned_survived": True, "tobin_returns_with_ned": True},
        ).to_dict()

        with tempfile.TemporaryDirectory() as temporary:
            loaded = self._load_fixture(Path(temporary), state)
            game = Game(TerminalUI(color=False, fast=True, output_fn=lambda _: None))
            game.state = loaded
            game._begin_part_two()

        self.assertTrue(loaded.flags["part_two_mara_present"])
        self.assertFalse(loaded.flags["part_two_tobin_present"])
