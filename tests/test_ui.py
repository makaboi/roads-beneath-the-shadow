import unittest
import os
import re
from unittest.mock import Mock, PropertyMock, patch

from roads_beneath_shadow.artwork import AnimatedArtwork
from roads_beneath_shadow.lighting import ART_PALETTES, Color
from roads_beneath_shadow.ui import InputClosed, TerminalUI


class TerminalUITests(unittest.TestCase):
    def test_eof_raises_input_closed_instead_of_looping(self) -> None:
        def closed_input(_: str) -> str:
            raise EOFError

        ui = TerminalUI(color=False, fast=True, input_fn=closed_input, output_fn=lambda _: None)

        with self.assertRaises(InputClosed):
            ui.choose("Menu", ["One", "Two"])

    def test_raw_menu_handles_closed_input_and_interrupt_keys(self) -> None:
        for key, exception in (("", InputClosed), ("\x04", InputClosed), ("\x03", KeyboardInterrupt)):
            with self.subTest(key=repr(key)):
                ui = TerminalUI(color=False, fast=True, output_fn=lambda _: None)
                with patch.object(ui, "_read_raw_key", side_effect=[key, "\r"]) as read_key:
                    with self.assertRaises(exception):
                        ui._choose_with_raw_keys("Menu", ["One", "Two"], False)
                read_key.assert_called_once_with()

    def test_raw_input_restores_terminal_after_read_interrupt(self) -> None:
        stream = Mock()
        stream.fileno.return_value = 7
        stream.read.side_effect = KeyboardInterrupt
        termios = Mock()
        previous = object()
        termios.tcgetattr.return_value = previous
        tty = Mock()
        with patch.dict("sys.modules", {"termios": termios, "tty": tty}):
            with patch("roads_beneath_shadow.ui.sys.stdin", stream):
                with self.assertRaises(KeyboardInterrupt):
                    TerminalUI._read_raw_key()
        tty.setraw.assert_called_once_with(7)
        termios.tcsetattr.assert_called_once_with(7, termios.TCSADRAIN, previous)

    def test_raw_menu_preserves_arrow_and_letter_navigation(self) -> None:
        for keys, expected in ((["s", "\r"], 2), (["\x1b[B", "d"], 2), (["w", "\r"], 3)):
            with self.subTest(keys=keys):
                ui = TerminalUI(color=False, fast=True, output_fn=lambda _: None)
                with patch.object(ui, "_read_raw_key", side_effect=keys):
                    with patch.object(ui, "_rewrite_choice_lines"):
                        self.assertEqual(ui._choose_with_raw_keys("Menu", ["One", "Two", "Three"], False), expected)

    def test_screen_reader_uses_numbered_line_prompts_in_an_interactive_terminal(self) -> None:
        output: list[str] = []
        prompts: list[str] = []

        def answer(prompt: str) -> str:
            prompts.append(prompt)
            return "2"

        ui = TerminalUI(
            color=False,
            fast=True,
            screen_reader=True,
            input_fn=answer,
            output_fn=output.append,
        )
        with patch.object(TerminalUI, "_interactive_terminal", new_callable=PropertyMock, return_value=True):
            with patch.object(ui, "_choose_with_raw_keys") as raw_menu:
                self.assertEqual(ui.choose("Menu", ["One", "Two"]), 2)
        raw_menu.assert_not_called()
        self.assertEqual(prompts, ["Enter your choice: "])
        self.assertIn("1. One", output)
        self.assertIn("2. Two", output)
        self.assertNotIn("\033", "\n".join(output))

    def test_wasd_navigation_selects_highlighted_option(self) -> None:
        answers = iter(["s", ""])
        output: list[str] = []
        ui = TerminalUI(
            color=False,
            fast=True,
            input_fn=lambda _: next(answers),
            output_fn=output.append,
        )

        self.assertEqual(ui.choose("Menu", ["One", "Two", "Three"]), 2)
        self.assertIn("> [2] Two", output)

    def test_arrow_sequence_and_right_key_select_an_option(self) -> None:
        answers = iter(["\x1b[B", "d"])
        ui = TerminalUI(
            color=False,
            fast=True,
            input_fn=lambda _: next(answers),
            output_fn=lambda _: None,
        )

        self.assertEqual(ui.choose("Menu", ["One", "Two"]), 2)

    def test_left_key_returns_from_a_menu_that_allows_back(self) -> None:
        ui = TerminalUI(
            color=False,
            fast=True,
            input_fn=lambda _: "a",
            output_fn=lambda _: None,
        )

        self.assertIsNone(ui.choose("Menu", ["One"], allow_back=True))

    def test_text_speed_controls_narration_delay(self) -> None:
        delays: list[float] = []
        ui = TerminalUI(
            color=False,
            text_speed="slow",
            output_fn=lambda _: None,
            sleep_fn=delays.append,
        )

        ui.narrate("First paragraph.\n\nSecond paragraph.")

        self.assertEqual(delays, [0.22, 0.22])
        ui.set_text_speed(0.5)
        self.assertEqual(ui.narration_delay, 0.5)

    def test_reduced_motion_collapses_animation_to_last_frame(self) -> None:
        output: list[str] = []
        ui = TerminalUI(
            color=False,
            reduced_motion=True,
            output_fn=output.append,
            terminal_size_fn=lambda _: os.terminal_size((40, 24)),
        )

        ui.animate(("FIRST", "FINAL"))

        self.assertNotIn("FIRST", "\n".join(output))
        self.assertIn("FINAL", "\n".join(output))

    def test_animation_offsets_keep_trimmed_frames_on_the_same_stage(self) -> None:
        output: list[str] = []
        ui = TerminalUI(color=False, output_fn=output.append, sleep_fn=lambda _: None)
        animation = AnimatedArtwork("LIT\nBASE", ("DIM", "LIT\nBASE"), frame_offsets=(1, 0))
        with patch.object(TerminalUI, "_interactive_terminal", new_callable=PropertyMock, return_value=True):
            with patch.object(ui, "clear", side_effect=lambda: output.append("<next>")):
                ui.art(animation)
        marker = output.index("<next>")
        dim, lit = output[:marker], output[marker + 1:]
        self.assertEqual(len(dim), len(lit))
        self.assertEqual(dim[0], "")
        self.assertEqual(dim[-1].strip(), "DIM")
        self.assertEqual(lit[-1].strip(), "BASE")

    def test_reduced_motion_uses_the_lit_still_without_animation_padding(self) -> None:
        output: list[str] = []
        ui = TerminalUI(color=False, reduced_motion=True, output_fn=output.append)
        ui.art(AnimatedArtwork("LIT", ("DIM", "LIT"), frame_offsets=(1, 0)))
        self.assertEqual([line.strip() for line in output], ["LIT"])

    def test_screen_reader_replaces_art_with_short_alt_text(self) -> None:
        output: list[str] = []
        ui = TerminalUI(color=False, fast=True, screen_reader=True, output_fn=output.append)

        ui.art("###\n###", alt_text="A rider blocks the buried road")

        self.assertEqual(output, ["[Scene: A rider blocks the buried road]"])

    def test_art_uses_a_centered_viewport_in_a_narrow_terminal(self) -> None:
        output: list[str] = []
        ui = TerminalUI(
            color=False,
            fast=True,
            output_fn=output.append,
            terminal_size_fn=lambda _: os.terminal_size((24, 24)),
        )

        ui.art("+--------------------------------------+\n|                 *                    |")

        self.assertTrue(output)
        self.assertTrue(all(len(line) <= 24 for line in output))

    def test_direct_prose_is_word_wrapped_in_a_narrow_terminal(self) -> None:
        output: list[str] = []
        ui = TerminalUI(
            color=False,
            fast=True,
            output_fn=output.append,
            terminal_size_fn=lambda *_: os.terminal_size((32, 24)),
        )

        ui.write("Ghorak raises the broken blade while the ancient doorway wakes behind him.")

        self.assertGreater(len(output), 1)
        self.assertTrue(all(len(line) <= 32 for line in output))

    def test_custom_sound_handler_can_fall_back_to_terminal_bell(self) -> None:
        output: list[str] = []
        cues: list[str] = []

        def unavailable(cue: str) -> bool:
            cues.append(cue)
            return False

        ui = TerminalUI(color=False, fast=True, sound=True, sound_fn=unavailable, output_fn=output.append)
        ui.sound("danger")

        self.assertEqual(cues, ["danger"])
        self.assertEqual(output, ["\a\a"])

    def test_empty_choice_list_is_rejected(self) -> None:
        ui = TerminalUI(color=False, fast=True, output_fn=lambda _: None)

        with self.assertRaises(ValueError):
            ui.choose("Menu", [])

    def test_art_lighting_preserves_every_character_and_uses_four_inks(self) -> None:
        plain: list[str] = []
        lit: list[str] = []
        art = "  .:-=+*#@\n   +###@+"
        for enabled, output in ((False, plain), (True, lit)):
            TerminalUI(color=enabled, fast=True, output_fn=output.append).art(art, Color.YELLOW)
        self.assertEqual([re.sub(r"\x1b\[[0-9;]*m", "", line) for line in lit], plain)
        for ink in ART_PALETTES[Color.YELLOW]:
            self.assertIn(f"\033[38;5;{ink}m", "\n".join(lit))
        self.assertNotIn("\033", "\n".join(plain))

    def test_colored_narrow_art_has_the_same_viewport_as_plain_art(self) -> None:
        plain: list[str] = []
        lit: list[str] = []
        art = ".:-=+*#@" * 9 + "\n" + "@#*+=-:." * 9
        for enabled, output in ((False, plain), (True, lit)):
            TerminalUI(
                color=enabled,
                fast=True,
                output_fn=output.append,
                terminal_size_fn=lambda _: os.terminal_size((24, 24)),
            ).art(art, Color.BLUE)
        visible = [re.sub(r"\x1b\[[0-9;]*m", "", line) for line in lit]
        self.assertEqual(visible, plain)
        self.assertTrue(all(len(line) <= 24 for line in visible))

    def test_nameplates_keep_uniform_ink_and_lighting_does_not_leak_into_prose(self) -> None:
        output: list[str] = []
        ui = TerminalUI(color=True, fast=True, output_fn=output.append)
        ui.art("[ LAST SEAL ]\n.*#@", Color.RED)
        ui.write("The vault listens.")
        self.assertIn(Color.RED, output[0])
        self.assertNotIn("\033[38;5;", output[0])
        self.assertTrue(output[1].endswith(Color.RESET))
        self.assertEqual(output[-1], "The vault listens." + Color.RESET)

    def test_screen_reader_never_receives_shaded_converter_marks(self) -> None:
        output: list[str] = []
        ui = TerminalUI(color=False, fast=True, screen_reader=True, output_fn=output.append)
        ui.art(".*#@", Color.YELLOW, alt_text="A lantern beneath an arch.")
        self.assertEqual(output, ["[Scene: A lantern beneath an arch.]"])


if __name__ == "__main__":
    unittest.main()
