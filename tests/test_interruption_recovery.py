"""Interrupted launches report only recovery verified on disk."""

import contextlib
import io
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from roads_beneath_shadow import __main__ as entrypoint
from roads_beneath_shadow.app import Game
from roads_beneath_shadow.checkpoint import CheckpointManager
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.profile import ProfileManager
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.settings import SettingsManager, UserSettings
from roads_beneath_shadow.ui import InputClosed, TerminalUI


class InterruptionRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.saves = SaveManager(self.root / "saves")
        self.checkpoints = CheckpointManager(self.saves.root)
        self.settings = SettingsManager(self.root / "settings.json")
        self.manual = self.state(name="Manual journey", journey="manual-journey")
        self.saves.save(2, self.manual)
        self.manual_bytes = self.saves._path(2).read_bytes()

    @staticmethod
    def state(*, name="Éowen", journey="active-journey"):
        return GameState(
            Character.from_origin(name, ORIGINS[0]),
            scene="bree_exploration", journey_id=journey,
        )

    def interrupted_launch(
        self, state, *, replace_failure=False, fail_once=False,
        autosave=True, interrupted_by=EOFError, graphical=False,
        toast_interrupt=False, constructor_interrupt=False,
    ):
        """Run the actual launcher, story checkpoint, and interruption handler."""
        output = []
        created = []
        replacements = []
        settings = UserSettings(color_mode="on", screen_reader=not graphical, autosave=autosave)
        self.settings.save(settings)
        original_replace = os.replace

        def replace(source, destination):
            if Path(destination) == self.checkpoints.path:
                replacements.append(Path(source))
                if replace_failure and (not fail_once or len(replacements) == 1):
                    raise OSError("simulated disk full")
            return original_replace(source, destination)

        def read(_prompt):
            raise interrupted_by()

        def make_ui(**options):
            options.pop("sound_fn", None)
            options["checkpoint_support"] = True
            ui = TerminalUI(**options, input_fn=read, output_fn=output.append)
            if toast_interrupt:
                ui.toast = lambda *_args, **_kwargs: (_ for _ in ()).throw(InputClosed())
            return ui

        class InterruptedGame(Game):
            def run(inner):
                if fail_once:
                    inner._record_checkpoint()
                inner._story_choice("RECOVERY BOUNDARY", ["Continue", "Wait"])

        def make_game(ui, **kwargs):
            if constructor_interrupt:
                raise interrupted_by()
            game = InterruptedGame(ui, saves=self.saves, checkpoints=self.checkpoints, **kwargs)
            game.state = state
            created.append(game)
            return game

        profile = ProfileManager(self.root / "profile.json")
        pixel = types.ModuleType("roads_beneath_shadow.pixel_ui")
        pixel.PixelUI = make_ui
        pixel.launch_pixel_game = lambda game, _ui, **_kwargs: game.run()
        captured = io.StringIO()
        with (
            patch.object(sys, "argv", ["roads_beneath_shadow", "--pixel" if graphical else "--screen-reader", "--fast"]),
            patch.object(entrypoint, "SettingsManager", return_value=self.settings),
            patch.object(entrypoint, "ProfileManager", return_value=profile),
            patch.object(entrypoint, "TerminalUI", side_effect=make_ui),
            patch.object(entrypoint, "Game", side_effect=make_game),
            patch.dict(sys.modules, {"roads_beneath_shadow.pixel_ui": pixel}),
            patch("roads_beneath_shadow.savegame.os.replace", side_effect=replace),
            contextlib.redirect_stdout(captured),
        ):
            entrypoint.main()
        transcript = "\n".join(output) + captured.getvalue()
        self.assertEqual(self.saves._path(2).read_bytes(), self.manual_bytes)
        self.assertFalse(list(self.saves.root.glob("*.tmp")))
        if not graphical:
            self.assertNotIn("\x1b", transcript)
        return transcript, created, replacements

    def test_failed_first_checkpoint_then_closed_input_reports_no_recovery(self):
        for interruption in (EOFError, KeyboardInterrupt):
            with self.subTest(interruption=interruption.__name__):
                transcript, _, replacements = self.interrupted_launch(
                    self.state(), replace_failure=True, interrupted_by=interruption,
                )
                self.assertEqual(len(replacements), 1)
                self.assertIn("Checkpoint could not be saved: simulated disk full", transcript)
                self.assertIn("No usable automatic checkpoint is available", transcript)
                self.assertIn("Unsaved progress was not kept", transcript)
                self.assertNotIn("Resume checkpoint restores", transcript)
                self.assertFalse(self.checkpoints.path.exists())

    def test_failed_replacement_then_closed_input_keeps_and_identifies_prior_decision(self):
        earlier = self.state()
        self.checkpoints.record(earlier)
        original = self.checkpoints.path.read_bytes()
        current = GameState.from_dict(earlier.to_dict())
        current.journal.append("An investigation finished after the earlier save.")
        transcript, _, replacements = self.interrupted_launch(current, replace_failure=True)
        self.assertEqual(len(replacements), 1)
        self.assertIn("Resume checkpoint restores the last saved story decision", transcript)
        self.assertIn("Progress since that save was not kept", transcript)
        self.assertEqual(self.checkpoints.path.read_bytes(), original)
        self.assertEqual(self.checkpoints.resume().to_dict(), earlier.to_dict())

    def test_failed_new_journey_checkpoint_names_the_other_saved_journey(self):
        earlier = self.state(name="Mira", journey="earlier-journey")
        self.checkpoints.record(earlier)
        original = self.checkpoints.path.read_bytes()
        transcript, _, _ = self.interrupted_launch(self.state(), replace_failure=True)
        self.assertIn("Unsaved progress in this journey was not kept", transcript)
        self.assertIn("Resume checkpoint restores Mira's saved journey", transcript)
        self.assertNotIn("restores the last saved story decision", transcript)
        self.assertEqual(self.checkpoints.path.read_bytes(), original)

    def test_damaged_or_unreadable_checkpoint_is_not_promised_after_failed_write(self):
        for damaged in (True, False):
            with self.subTest(damaged=damaged):
                if damaged:
                    self.checkpoints.path.write_bytes(b"damaged checkpoint")
                else:
                    self.checkpoints.record(self.state())
                original = self.checkpoints.path.read_bytes()
                current = self.state()
                current.journal.append("Unsaved clue")
                reader = contextlib.nullcontext() if damaged else patch.object(
                    self.checkpoints, "resume", side_effect=PermissionError("unreadable checkpoint"),
                )
                with reader:
                    transcript, _, _ = self.interrupted_launch(current, replace_failure=True)
                self.assertIn("No usable automatic checkpoint is available", transcript)
                self.assertNotIn("Resume checkpoint restores", transcript)
                self.assertEqual(self.checkpoints.path.read_bytes(), original)

    def test_successful_checkpoint_then_interruption_offers_actual_saved_state(self):
        current = self.state()
        transcript, _, replacements = self.interrupted_launch(current)
        self.assertEqual(len(replacements), 1)
        self.assertIn("Resume checkpoint restores the last saved story decision", transcript)
        self.assertNotIn("was not kept", transcript)
        self.assertEqual(self.checkpoints.resume().to_dict(), current.to_dict())

    def test_disabled_autosave_still_identifies_existing_checkpoint_without_updating_it(self):
        earlier = self.state()
        self.checkpoints.record(earlier)
        original = self.checkpoints.path.read_bytes()
        current = GameState.from_dict(earlier.to_dict())
        current.character.hp -= 7
        transcript, _, replacements = self.interrupted_launch(current, autosave=False)
        self.assertEqual(replacements, [])
        self.assertIn("Resume checkpoint restores the last saved story decision", transcript)
        self.assertIn("Progress since that save was not kept", transcript)
        self.assertEqual(self.checkpoints.path.read_bytes(), original)

    def test_failed_write_followed_by_successful_retry_reports_the_new_valid_checkpoint(self):
        current = self.state()
        transcript, _, replacements = self.interrupted_launch(
            current, replace_failure=True, fail_once=True,
        )
        self.assertEqual(len(replacements), 2)
        self.assertIn("Checkpoint could not be saved: simulated disk full", transcript)
        self.assertIn("Resume checkpoint restores the last saved story decision", transcript)
        self.assertNotIn("was not kept", transcript)
        self.assertEqual(self.checkpoints.resume().to_dict(), current.to_dict())

    def test_interrupting_the_saved_toast_does_not_hide_a_completed_checkpoint(self):
        current = self.state()
        transcript, _, replacements = self.interrupted_launch(current, toast_interrupt=True)
        self.assertEqual(len(replacements), 1)
        self.assertIn("Resume checkpoint restores the last saved story decision", transcript)
        self.assertEqual(self.checkpoints.resume().to_dict(), current.to_dict())

    def test_constructor_interruption_makes_no_unverified_recovery_promise(self):
        for interruption in (InputClosed, KeyboardInterrupt):
            with self.subTest(interruption=interruption.__name__):
                transcript, created, replacements = self.interrupted_launch(
                    self.state(), interrupted_by=interruption, constructor_interrupt=True,
                )
                self.assertEqual((created, replacements), ([], []))
                self.assertIn("Automatic recovery could not be checked", transcript)
                self.assertNotIn("Resume checkpoint restores", transcript)

    def test_graphical_launcher_prints_truthful_failed_checkpoint_notice(self):
        transcript, _, replacements = self.interrupted_launch(
            self.state(), replace_failure=True, graphical=True,
        )
        self.assertEqual(len(replacements), 1)
        self.assertIn("Your journey has paused. No usable automatic checkpoint is available", transcript)
        self.assertNotIn("Resume checkpoint restores", transcript)

    def test_saved_ending_guidance_matches_the_main_menu_revisit_action(self):
        ending = self.state(name="Mira", journey="ending-journey")
        ending.scene = "complete"
        ending.ending = "fellowship"
        self.checkpoints.record(ending)
        original = self.checkpoints.path.read_bytes()
        for state in (None, self.state(), ending):
            with self.subTest(active_journey=state.journey_id if state else None):
                transcript, _, replacements = self.interrupted_launch(state, autosave=False)
                self.assertEqual(replacements, [])
                self.assertIn("Revisit", transcript)
                self.assertIn("saved ending from the main menu", transcript)
                self.assertNotIn("Resume checkpoint restores", transcript)
                self.assertEqual(self.checkpoints.path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
