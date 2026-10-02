"""Numeric-looking keys and oversized pasted numbers leave menus usable."""

import random
import unittest
from unittest.mock import patch

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.ui import TerminalUI, choice_number


class ChoiceInputTests(unittest.TestCase):
    def test_decimal_choices_accept_arabic_digits_and_arbitrarily_many_leading_zeros(self):
        for answer, expected in (("2", 2), ("٢", 2), ("٠٠٢", 2), ("0" * 5_000 + "٢", 2)):
            with self.subTest(answer=answer[:12], length=len(answer)):
                answers = iter((answer,))
                ui = TerminalUI(color=False, fast=True, input_fn=lambda _: next(answers), output_fn=lambda _: None)
                self.assertEqual(ui.choose("Menu", ["One", "Two", "Three"]), expected)

    def test_superscript_and_oversized_pastes_are_ignored_before_a_valid_choice(self):
        answers = iter(("²", "9" * 10_000, "0" * 5_000, "٢"))
        output = []
        ui = TerminalUI(color=False, fast=True, input_fn=lambda _: next(answers), output_fn=output.append)

        self.assertEqual(ui.choose("Menu", ["One", "Two", "Three"]), 2)
        self.assertEqual(sum(line == "Choose one of the listed options." for line in output), 3)

    def test_raw_key_menu_ignores_the_azerty_superscript_key_and_accepts_an_arabic_key(self):
        ui = TerminalUI(color=False, fast=True, output_fn=lambda _: None)
        with patch.object(ui, "_read_raw_key", side_effect=("²", "٢")) as read:
            self.assertEqual(ui._choose_with_raw_keys("Menu", ["One", "Two"], False), 2)
        self.assertEqual(read.call_count, 2)

    def test_story_prompt_recovers_from_numeric_looking_and_oversized_input_without_state_costs(self):
        answers = iter(("²", "9" * 10_000, "0" * 5_000 + "٢"))
        ui = TerminalUI(color=False, fast=True, input_fn=lambda _: next(answers), output_fn=lambda _: None)
        game = Game(ui, rng=random.Random(731))
        game.state = GameState(Character.from_origin("Mira", ORIGINS[0]))
        state, rng = game.state.to_dict(), game.rng.getstate()

        self.assertEqual(game._story_choice("Choose a path", ["One", "Two"]), 2)
        self.assertEqual(game.state.to_dict(), state)
        self.assertEqual(game.rng.getstate(), rng)

    def test_numeric_parser_rejects_zero_signs_nondecimal_numbers_and_out_of_range_input(self):
        for text in ("", "0", "٠", "²", "Ⅲ", "+2", "-2", "2.0", "4", "9" * 10_000):
            with self.subTest(text=text[:12]):
                self.assertIsNone(choice_number(text, 3))


if __name__ == "__main__":
    unittest.main()
