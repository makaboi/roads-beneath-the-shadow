"""A launch pacing override stays separate from explicitly saved preferences."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from roads_beneath_shadow import __main__ as entrypoint
from roads_beneath_shadow.app import Game
from roads_beneath_shadow.audio import SoundPlayer
from roads_beneath_shadow.settings import SettingsManager, UserSettings
from roads_beneath_shadow.ui import TerminalUI


class LaunchTextSpeedTests(unittest.TestCase):
    def run_terminal(self, directory, answers, *, override=None):
        manager = SettingsManager(directory / "settings.json")
        manager.save(UserSettings())
        output = []
        interfaces = []
        persisted_at_input = []
        selections = iter(answers)

        def read(_prompt):
            persisted_at_input.append(manager.load())
            return next(selections)

        def interface(**options):
            ui = TerminalUI(**options, input_fn=read, output_fn=output.append)
            interfaces.append(ui)
            return ui

        arguments = ["roads-beneath-shadow", "--terminal", "--fast"]
        if override is not None:
            arguments.extend(("--text-speed", override))
        with patch.dict(os.environ, {"RBS_SAVE_DIR": str(directory / "saves")}), patch.object(
            sys, "argv", arguments
        ), patch.object(entrypoint, "TerminalUI", side_effect=interface), patch.object(
            SoundPlayer, "play", return_value=True
        ):
            entrypoint.main()
        return manager.load(), interfaces[0], "\n".join(output), persisted_at_input

    def test_main_override_survives_unrelated_sound_toggle_without_being_saved(self):
        with tempfile.TemporaryDirectory() as temporary:
            saved, ui, transcript, _ = self.run_terminal(
                Path(temporary), ("5", "1", "8", "6"), override="slow"
            )
        self.assertEqual(ui.text_speed, "slow")
        self.assertIn("Text speed: Slow", transcript)
        self.assertNotIn("Text speed: Normal", transcript)
        self.assertTrue(saved.sound)
        self.assertEqual(saved.text_speed, "normal")

    def test_explicit_text_speed_change_cycles_from_override_and_persists(self):
        with tempfile.TemporaryDirectory() as temporary:
            saved, ui, transcript, observations = self.run_terminal(
                Path(temporary), ("5", "1", "3", "8", "6"), override="fast"
            )
        self.assertTrue(observations[2].sound)
        self.assertEqual(observations[2].text_speed, "normal")
        self.assertEqual(observations[3].text_speed, "instant")
        self.assertIn("Text speed: Fast", transcript)
        self.assertIn("Text speed: Instant", transcript)
        self.assertEqual(ui.text_speed, "instant")
        self.assertEqual(saved.text_speed, "instant")

    def test_unrelated_save_without_override_keeps_normal_runtime_and_saved_speed(self):
        with tempfile.TemporaryDirectory() as temporary:
            saved, ui, transcript, _ = self.run_terminal(
                Path(temporary), ("5", "1", "8", "6")
            )
        self.assertTrue(saved.sound)
        self.assertEqual(ui.text_speed, "normal")
        self.assertEqual(saved.text_speed, "normal")
        self.assertIn("Text speed: Normal", transcript)

    def test_numeric_runtime_delay_uses_saved_named_speed_for_settings_cycle(self):
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            manager = SettingsManager(directory / "settings.json")
            output = []
            selections = iter(("3", "7"))
            ui = TerminalUI(color=False, fast=True, text_speed=0.5,
                            input_fn=lambda _prompt: next(selections), output_fn=output.append)
            with patch.dict(os.environ, {"RBS_SAVE_DIR": str(directory / "saves")}):
                game = Game(ui, settings_manager=manager,
                            user_settings=UserSettings(text_speed="slow"))
                game._settings()
            self.assertIn("Text speed: Slow", "\n".join(output))
            self.assertEqual(ui.text_speed, "normal")
            self.assertEqual(manager.load().text_speed, "normal")


if __name__ == "__main__":
    unittest.main()
