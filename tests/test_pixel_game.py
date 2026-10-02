"""Regression coverage for the pixel presentation's shared game boundary."""

import contextlib
import io
import json
import os
import random
import sys
import tempfile
import threading
import time
import types
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from roads_beneath_shadow import __main__ as entrypoint
from roads_beneath_shadow.app import Game
from roads_beneath_shadow.content import CHAPTER_ONE_CHOICES, ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.settings import UserSettings
from roads_beneath_shadow.ui import InputClosed, TerminalUI
from tests.helpers import EpisodePlayer


def play_pixel_opening(screenshot: Path):
    """Use real SDL events to create a traveler and win the opening battle."""
    from roads_beneath_shadow.pixel_ui import PixelUI, PixelWindow

    with tempfile.TemporaryDirectory() as temporary:
        ui = PixelUI(fast=True, text_speed="instant", sound=False)
        game = Game(ui, saves=SaveManager(Path(temporary)), rng=random.Random(5))
        ui.state_provider = lambda: game.state
        player = EpisodePlayer()
        errors = []
        request_labels = []
        history_cursor = 0
        main_menu_visits = 0
        combat_captured = False

        def play():
            try:
                game.run()
            except InputClosed:
                pass
            except Exception as error:
                errors.append(error)

        with patch.dict(os.environ, {"SDL_VIDEODRIVER": "dummy", "SDL_AUDIODRIVER": "dummy"}):
            window = PixelWindow(ui)
            worker = threading.Thread(target=play, daemon=True)
            worker.start()
            deadline = time.monotonic() + 15
            try:
                while worker.is_alive() and time.monotonic() < deadline:
                    window.drain()
                    window.render()
                    request = window.request
                    if request is not None:
                        request_labels.append(request.label)
                        context = "\n".join(
                            [text for text, _color, _bold in window.history[history_cursor:]]
                            + [request.label]
                            + [f"[{number}] {option}" for number, option in enumerate(request.options, 1)]
                        )
                        history_cursor = len(window.history)
                        if request.label == "Choose your action" and not combat_captured:
                            screenshot.parent.mkdir(parents=True, exist_ok=True)
                            window.pg.image.save(window.screen, str(screenshot))
                            combat_captured = True
                        if request.kind == "pause":
                            answer = ""
                        elif request.label == "MAIN MENU":
                            main_menu_visits += 1
                            answer = "1" if main_menu_visits == 1 else str(len(request.options))
                        elif request.story and game.state.scene == "aftermath":
                            answer = "m"
                        else:
                            answer = player._answer(request.label, context)

                        pg = window.pg
                        if request.kind == "text":
                            window.handle_event(pg.event.Event(pg.TEXTINPUT, text=answer))
                            window.handle_event(pg.event.Event(pg.KEYDOWN, key=pg.K_RETURN, unicode="\r"))
                        elif request.kind == "pause":
                            window.handle_event(pg.event.Event(pg.KEYDOWN, key=pg.K_RETURN, unicode="\r"))
                        else:
                            key = pg.K_0 + int(answer) if answer.isdigit() else ord(answer)
                            window.handle_event(pg.event.Event(pg.KEYDOWN, key=key, unicode=answer))
                    window.clock.tick(120)
                window.drain()
                if worker.is_alive():
                    raise AssertionError("The graphical journey did not finish within 15 seconds")
                if errors:
                    raise AssertionError(f"The graphical worker failed: {errors[0]}") from errors[0]
                if not combat_captured:
                    raise AssertionError("The graphical journey never reached a combat action")
                transcript = "\n".join(text for text, _color, _bold in window.history)
                return game.state, request_labels, transcript
            finally:
                ui.close()
                worker.join(timeout=1)
                window.pg.quit()


class ScriptedStoryUI(TerminalUI):
    """Exercise the graphical hook while using the real shared utility menus."""

    def __init__(self, story_actions, menu_answers=()):
        self.story_actions = iter(story_actions)
        self.menu_answers = iter(menu_answers)
        self.story_calls = []
        self.prompts = []
        self.output = []
        super().__init__(
            color=False,
            fast=True,
            input_fn=self._read,
            output_fn=self.output.append,
        )

    def _read(self, prompt):
        self.prompts.append(prompt)
        return next(self.menu_answers)

    def choose_story(self, heading, options):
        self.story_calls.append((heading, tuple(options)))
        return next(self.story_actions)


class PixelGameIntegrationTests(unittest.TestCase):
    @staticmethod
    def _state():
        state = GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            scene="chapter1_decision",
            journey_id="pixel-compatibility-journey",
            play_minutes=17,
        )
        state.flags["remembered_lesson"] = True
        state.add_quest("Keep the silver star from the Shadow")
        state.completed_quests.append("Read Calenor's letter")
        state.add_journal("The messenger named the north gate.")
        return state

    def test_graphical_integer_and_string_choices_advance_original_story_branches(self):
        branches = (
            "branch_fight",
            "branch_hide",
            "branch_search",
            "branch_escape",
            "branch_question",
        )
        for index, scene in enumerate(branches, 1):
            for action in (index, str(index)):
                with self.subTest(action=action):
                    ui = ScriptedStoryUI([action])
                    game = Game(ui)
                    game.state = self._state()

                    self.assertTrue(game._chapter_one_decision())

                    self.assertEqual(game.state.scene, scene)
                    self.assertEqual(
                        ui.story_calls,
                        [("WHAT WILL YOU DO?", tuple(CHAPTER_ONE_CHOICES))],
                    )
                    self.assertEqual(ui.prompts, [])

    def test_invalid_graphical_actions_retry_without_advancing_story(self):
        ui = ScriptedStoryUI([0, 6, "unknown", 3])
        game = Game(ui)
        game.state = self._state()

        self.assertTrue(game._chapter_one_decision())

        self.assertEqual(game.state.scene, "branch_search")
        self.assertEqual(len(ui.story_calls), 4)
        self.assertEqual(
            ui.output.count("Choose a number or one of the listed commands."), 3
        )

    def test_graphical_main_menu_actions_keep_unfinished_journey(self):
        for action in (None, "m", "menu", "q", "quit"):
            with self.subTest(action=action):
                ui = ScriptedStoryUI([action])
                game = Game(ui)
                game.state = self._state()
                before = game.state.to_dict()

                game._run_journey()

                self.assertEqual(game.state.to_dict(), before)
                self.assertEqual(len(ui.story_calls), 1)
                self.assertEqual(ui.prompts, [])

    def test_graphical_utilities_save_equipment_and_resume_at_same_choice(self):
        with tempfile.TemporaryDirectory() as temporary:
            saves = SaveManager(Path(temporary))
            # Equip the cleaver, return from inventory, then save to slot two.
            ui = ScriptedStoryUI(["i", "j", "c", "s", 2], ["1", "3", "3", "2"])
            game = Game(ui, saves=saves)
            game.state = self._state()
            game.state.character.add_item("orc_cleaver")

            self.assertTrue(game._chapter_one_decision())

            transcript = "\n".join(ui.output)
            self.assertEqual(game.state.scene, "branch_hide")
            self.assertEqual(game.state.character.weapon, "orc_cleaver")
            self.assertIn("Equipped Orc Cleaver.", transcript)
            self.assertIn("Keep the silver star from the Shadow", transcript)
            self.assertIn("Read Calenor's letter", transcript)
            self.assertIn("The messenger named the north gate.", transcript)
            self.assertIn("Strength 2", transcript)
            self.assertIn("Journey saved in slot 2.", transcript)

            saved = saves.load(2)
            self.assertEqual(saved.scene, "chapter1_decision")
            self.assertEqual(saved.character.weapon, "orc_cleaver")
            self.assertEqual(saved.journey_id, game.state.journey_id)
            self.assertEqual(saved.flags, game.state.flags)
            self.assertEqual(saved.journal, game.state.journal)
            self.assertEqual(saved.play_minutes, 17)

            resumed_ui = ScriptedStoryUI([5], ["2"])
            resumed = Game(resumed_ui, saves=SaveManager(Path(temporary)))
            self.assertTrue(resumed._load_menu())
            self.assertEqual(resumed.state.to_dict(), saved.to_dict())
            self.assertTrue(resumed._chapter_one_decision())
            self.assertEqual(resumed.state.scene, "branch_question")
            self.assertEqual(resumed.state.character.weapon, "orc_cleaver")
            self.assertIn("Welcome back, Arin.", resumed_ui.output)

    def test_declining_graphical_save_overwrite_preserves_existing_journey(self):
        with tempfile.TemporaryDirectory() as temporary:
            saves = SaveManager(Path(temporary))
            previous = self._state()
            previous.character.name = "Mira"
            save_path = saves.save(1, previous)
            before = save_path.read_bytes()
            ui = ScriptedStoryUI(["save", 4], ["1", "2"])
            game = Game(ui, saves=saves)
            game.state = self._state()

            self.assertTrue(game._chapter_one_decision())

            self.assertEqual(game.state.scene, "branch_escape")
            self.assertEqual(save_path.read_bytes(), before)
            self.assertEqual(saves.load(1).character.name, "Mira")

    def test_original_version_two_save_continues_through_graphical_choices(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            original = self._state()
            original.character.hp = 11
            original.character.corruption = 2
            original.character.add_item("silver_star")
            payload = original.to_dict()
            self.assertEqual(payload["save_version"], 2)
            # Pre-journey-ID terminal saves also remain loadable in pixel mode.
            payload.pop("journey_id")
            (root / "slot_1.json").write_text(
                json.dumps({"saved_at": "2026-09-01T12:00:00+00:00", "state": payload}),
                encoding="utf-8",
            )
            ui = ScriptedStoryUI([3], ["1"])
            game = Game(ui, saves=SaveManager(root))

            self.assertTrue(game._load_menu())
            migrated_id = game.state.journey_id
            self.assertEqual(game.state.character, original.character)
            self.assertEqual(game.state.journal, original.journal)
            self.assertEqual(game.state.flags, original.flags)
            self.assertTrue(game._chapter_one_decision())
            self.assertEqual(game.state.scene, "branch_search")
            saved_path = game.saves.save(2, game.state)
            reloaded = SaveManager(root).load(2)

            self.assertEqual(reloaded.to_dict(), game.state.to_dict())
            self.assertEqual(reloaded.journey_id, migrated_id)
            self.assertEqual(json.loads(saved_path.read_text())["state"]["save_version"], 2)

    def test_terminal_ui_without_graphical_hook_still_advances_story(self):
        output = []
        game = Game(
            TerminalUI(
                color=False,
                fast=True,
                input_fn=lambda _: "2",
                output_fn=output.append,
            )
        )
        game.state = self._state()

        self.assertTrue(game._chapter_one_decision())

        self.assertEqual(game.state.scene, "branch_hide")
        self.assertIn("[2] " + CHAPTER_ONE_CHOICES[1], output)
        self.assertTrue(any("[S] Save" in line for line in output))

    def test_real_pixel_window_creates_traveler_wins_battle_and_returns_to_menu(self):
        with tempfile.TemporaryDirectory() as temporary:
            screenshot = Path(temporary) / "combat.png"

            state, labels, transcript = play_pixel_opening(screenshot)

            self.assertEqual(screenshot.read_bytes()[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(state.character.name, "Arin")
            self.assertEqual(state.scene, "aftermath")
            self.assertTrue(state.flags["stood_with_mara"])
            self.assertTrue(state.flags["aftermath_setup"])
            self.assertNotIn("mara_saved_player", state.flags)
            self.assertGreater(state.character.hp, 0)
            self.assertGreaterEqual(labels.count("Choose your action"), 2)
            self.assertEqual(labels.count("MAIN MENU"), 2)
            self.assertIn("Your committed blow deals", transcript)
            self.assertIn("The last enemy crashes to the floor.", transcript)
            self.assertIn("May a star shine upon your road.", transcript)


class PixelCommandLineTests(unittest.TestCase):
    def test_parser_supports_pixel_terminal_and_screenshot_modes(self):
        parser = entrypoint.build_parser()
        defaults = parser.parse_args([])
        self.assertFalse(defaults.pixel)
        self.assertFalse(defaults.terminal)
        self.assertIsNone(defaults.screenshot)
        self.assertTrue(parser.parse_args(["--pixel"]).pixel)
        self.assertTrue(parser.parse_args(["--terminal"]).terminal)
        self.assertEqual(
            parser.parse_args(["--screenshot", "preview.png"]).screenshot,
            Path("preview.png"),
        )

    def test_parser_rejects_conflicting_presentation_modes(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            entrypoint.build_parser().parse_args(["--pixel", "--terminal"])
        self.assertEqual(error.exception.code, 2)

    def test_screenshot_rejects_terminal_or_screen_reader_launches(self):
        for mode in ("--terminal", "--screen-reader"):
            with self.subTest(mode=mode):
                stderr = io.StringIO()
                with patch.object(sys, "argv", ["roads-beneath-shadow", mode, "--screenshot", "preview.png"]):
                    with contextlib.redirect_stderr(stderr), self.assertRaises(SystemExit) as error:
                        entrypoint.main()
                self.assertEqual(error.exception.code, 2)
                self.assertIn("--screenshot requires pixel-art mode", stderr.getvalue())

    def test_default_pixel_and_explicit_modes_dispatch_to_correct_presentation(self):
        cases = (
            ([], False, None),
            (["--pixel"], False, None),
            (["--terminal"], True, None),
            (["--screen-reader"], True, None),
            (["--pixel", "--screen-reader"], False, None),
            (["--screenshot", "preview.png"], False, Path("preview.png")),
        )
        for arguments, terminal, screenshot in cases:
            with self.subTest(arguments=arguments):
                pixel_module = types.ModuleType("roads_beneath_shadow.pixel_ui")
                pixel_module.PixelUI = MagicMock(name="PixelUI")
                pixel_module.launch_pixel_game = MagicMock(name="launch_pixel_game")
                with contextlib.ExitStack() as stack:
                    stack.enter_context(patch.dict(sys.modules, {pixel_module.__name__: pixel_module}))
                    stack.enter_context(patch.object(sys, "argv", ["roads-beneath-shadow", *arguments]))
                    settings_manager = stack.enter_context(patch.object(entrypoint, "SettingsManager"))
                    stack.enter_context(patch.object(entrypoint, "ProfileManager"))
                    terminal_ui = stack.enter_context(patch.object(entrypoint, "TerminalUI"))
                    game_type = stack.enter_context(patch.object(entrypoint, "Game"))
                    settings_manager.return_value.load.return_value = UserSettings()
                    entrypoint.main()

                game = game_type.return_value
                if terminal:
                    terminal_ui.assert_called_once()
                    game.run.assert_called_once_with()
                    pixel_module.PixelUI.assert_not_called()
                    pixel_module.launch_pixel_game.assert_not_called()
                else:
                    terminal_ui.assert_not_called()
                    pixel_module.PixelUI.assert_called_once()
                    game.run.assert_not_called()
                    pixel_module.launch_pixel_game.assert_called_once_with(
                        game, pixel_module.PixelUI.return_value, screenshot=screenshot
                    )


if __name__ == "__main__":
    unittest.main()
