"""Last Lantern recovery respects difficulty, choice, and saved checkpoints."""

import tempfile
import unittest
from pathlib import Path

from roads_beneath_shadow.combat import CombatDifficulty
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.part_two import PartTwoEpisode
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.ui import TerminalUI


class LanternRecoveryTests(unittest.TestCase):
    @staticmethod
    def state():
        state = GameState(Character.from_origin("Arin", ORIGINS[0]), chapter=2, scene="part2_vigil")
        state.character.hp = 1
        state.character.focus = 0
        state.character.hope = 4
        state.character.corruption = 2
        state.character.mara_trust = 3
        state.character.tobin_trust = 2
        state.play_minutes = 90
        return state

    def episode(self, labels, difficulty=CombatDifficulty.NORMAL, menus=None):
        answers = iter(labels)

        def choose(heading, options):
            if menus is not None:
                menus.append(tuple(options))
            label = next(answers)
            if label is None:
                return None
            return next(index + 1 for index, option in enumerate(options) if label in option)

        return PartTwoEpisode(
            TerminalUI(color=False, fast=True, output_fn=lambda _: None),
            choose,
            lambda *_: self.fail("Rest must not start combat"),
            difficulty_provider=lambda: difficulty,
        )

    def test_recovery_has_an_explicit_once_only_choice_and_difficulty_amount(self):
        for difficulty, expected_health in (
            (CombatDifficulty.STORY, 28), (CombatDifficulty.NORMAL, 15), (CombatDifficulty.HARD, 10),
        ):
            with self.subTest(difficulty=difficulty):
                state = self.state()
                social_before = (state.character.hope, state.character.corruption, state.character.mara_trust, state.character.tobin_trust)
                menus = []
                self.assertTrue(self.episode(("Rest and tend", "Enter the Last Seal"), difficulty, menus).run_scene(state))
                self.assertEqual((state.character.hp, state.character.focus), (expected_health, 3))
                self.assertEqual((state.play_minutes, state.scene), (96, "part2_last_seal"))
                self.assertTrue(state.flags["part2_vigil_rest"])
                self.assertEqual(len(state.journal), 1)
                self.assertTrue(any(option.startswith("Rest and tend your wounds") for option in menus[0]))
                self.assertFalse(any(option.startswith("Rest and tend your wounds") for option in menus[-1]))
                self.assertEqual((state.character.hope, state.character.corruption, state.character.mara_trust, state.character.tobin_trust), social_before)

    def test_skipping_or_leaving_before_choice_preserves_all_character_state(self):
        for choice in (None, "Enter the Last Seal"):
            with self.subTest(choice=choice):
                state = self.state()
                before = state.to_dict()
                self.assertEqual(self.episode((choice,)).run_scene(state), choice is not None)
                if choice is not None:
                    before["scene"] = "part2_last_seal"
                self.assertEqual(state.to_dict(), before)

    def test_saved_rest_cannot_be_farmed_after_new_injuries_and_reentry(self):
        state = self.state()
        self.assertFalse(self.episode(("Rest and tend", None)).run_scene(state))
        with tempfile.TemporaryDirectory() as directory:
            saves = SaveManager(Path(directory))
            saves.save(1, state)
            state = saves.load(1)
        state.character.hp = 1
        state.character.focus = 0
        menus = []
        self.assertTrue(self.episode(("Enter the Last Seal",), menus=menus).run_scene(state))
        self.assertEqual((state.character.hp, state.character.focus, state.play_minutes), (1, 0, 96))
        self.assertFalse(any(option.startswith("Rest and tend your wounds") for option in menus[0]))
        self.assertEqual(len(state.journal), 1)

    def test_recovery_clamps_health_and_is_available_for_focus_alone(self):
        state = self.state()
        state.character.hp = state.character.max_hp
        self.assertTrue(self.episode(("Rest and tend", "Enter the Last Seal")).run_scene(state))
        self.assertEqual((state.character.hp, state.character.focus), (28, 3))
        state = self.state()
        state.character.hp = 27
        self.assertTrue(self.episode(("Rest and tend", "Enter the Last Seal")).run_scene(state))
        self.assertEqual(state.character.hp, 28)

    def test_uninjured_traveler_has_no_rest_option_and_old_saves_can_choose_rest(self):
        state = self.state()
        state.character.hp = state.character.max_hp
        state.character.focus = state.character.max_focus
        menus = []
        self.assertTrue(self.episode(("Enter the Last Seal",), menus=menus).run_scene(state))
        self.assertFalse(any(option.startswith("Rest and tend your wounds") for option in menus[0]))
        legacy = self.state().to_dict()
        self.assertNotIn("part2_vigil_rest", legacy["flags"])
        restored = GameState.from_dict(legacy)
        self.assertTrue(self.episode(("Rest and tend", "Enter the Last Seal")).run_scene(restored))
        self.assertTrue(restored.flags["part2_vigil_rest"])


if __name__ == "__main__":
    unittest.main()
