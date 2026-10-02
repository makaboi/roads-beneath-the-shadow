"""Graphical recovery and save panels preserve the story and manual slots."""

import random
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.checkpoint import CheckpointManager
from roads_beneath_shadow.combat import CombatConfig
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, Enemy, GameState
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.settings import UserSettings
from roads_beneath_shadow.ui import TerminalUI


class RecoveryUI(TerminalUI):
    supports_checkpoints = True

    def __init__(self, labels=(), *, selector=None):
        self.labels = iter(labels)
        self.selector = selector
        self.output = []
        self.toasts = []
        self.menus = []
        self.pauses = 0
        super().__init__(color=False, fast=True, output_fn=self.output.append)

    def choose(self, title, options, *, allow_back=False):
        self.menus.append((title, tuple(options)))
        if self.selector:
            return self.selector(title, options)
        label = next(self.labels)
        if label is None:
            return None
        return next(index + 1 for index, option in enumerate(options) if label in option)

    def toast(self, text, *, kind="notice"):
        self.toasts.append(text)

    def pause(self, message=""):
        self.pauses += 1


class SavePanelUI(RecoveryUI):
    def __init__(self, results=(), labels=()):
        super().__init__(labels)
        self.results = iter(results)
        self.panels = []

    def show_panel(self, kind, data):
        self.panels.append((kind, deepcopy(data)))
        return next(self.results)


class CheckpointIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.saves = SaveManager(self.root)
        self.checkpoints = CheckpointManager(self.root)

    @staticmethod
    def state(name="Arin", *, origin=0, scene="chapter1_decision"):
        return GameState(Character.from_origin(name, ORIGINS[origin]), scene=scene)

    def game(self, ui, **kwargs):
        return Game(ui, saves=self.saves, checkpoints=self.checkpoints, rng=random.Random(12), **kwargs)

    def test_scene_transitions_checkpoint_resolved_combat_without_writing_mid_turn(self):
        before = self.state("Manual memory")
        self.saves.save(1, before)
        manual_bytes = self.saves._path(1).read_bytes()
        initial = self.state(scene="branch_fight")
        observed_combat_health = []

        def choose(title, options):
            self.assertEqual(title, "Choose your action")
            recorded = self.checkpoints.resume()
            self.assertEqual(recorded.scene, "branch_fight")
            self.assertEqual(recorded.character.hp, initial.character.max_hp)
            observed_combat_health.append(game.state.character.hp)
            return 1

        ui = RecoveryUI(selector=choose)

        class TwoSceneGame(Game):
            def _branch_fight(inner):
                inner.combat.run(inner.state, [Enemy("Practice", 100, 100, 4, 4)], CombatConfig(max_rounds=2))
                inner.state.flags["combat_resolved"] = True
                inner.state.scene = "aftermath"

            def _aftermath(inner):
                recorded = inner.checkpoints.resume()
                self.assertTrue(recorded.flags["combat_resolved"])
                self.assertEqual(recorded.to_dict(), inner.state.to_dict())
                return False

        game = TwoSceneGame(ui, saves=self.saves, checkpoints=self.checkpoints, rng=random.Random(12))
        game.state = initial
        game._run_journey()
        self.assertEqual(observed_combat_health, [28, 25])
        self.assertEqual(self.checkpoints.resume().scene, "aftermath")
        self.assertEqual(self.saves._path(1).read_bytes(), manual_bytes)
        self.assertEqual(ui.toasts, ["Checkpoint saved.", "Checkpoint saved."])

    def test_identical_checkpoint_does_not_show_another_saved_toast(self):
        ui = RecoveryUI()
        game = self.game(ui)
        game.state = self.state()
        game._record_checkpoint()
        recorded = self.checkpoints.path.read_bytes()
        game._record_checkpoint()
        self.assertEqual(self.checkpoints.path.read_bytes(), recorded)
        self.assertEqual(ui.toasts, ["Checkpoint saved."])

    def test_exploration_checkpoint_keeps_completed_clues_before_leaving_the_map(self):
        ui = RecoveryUI()
        choices = iter((1, 1, None))
        ui.choose_story = lambda heading, options: next(choices)
        game = self.game(ui)
        game.state = self.state(scene="bree_exploration")
        self.assertFalse(game._bree_exploration())
        restored = self.checkpoints.resume()
        self.assertEqual(restored.scene, "bree_exploration")
        self.assertTrue(restored.flags["identified_ghorak_mark"])
        self.assertIn("messenger_room", restored.visited)
        self.assertIn("black_arrowhead", restored.character.inventory)
        self.assertEqual(restored.to_dict(), game.state.to_dict())
        self.assertEqual(self.saves.all_slots(), [None, None, None])

    def test_disabled_autosave_or_terminal_capability_creates_no_checkpoint(self):
        for ui, settings in (
            (RecoveryUI(), UserSettings(autosave=False)),
            (TerminalUI(color=False, fast=True, output_fn=lambda _: None), UserSettings()),
        ):
            with self.subTest(ui=type(ui).__name__, autosave=settings.autosave):
                game = self.game(ui, user_settings=settings)
                game.state = self.state()
                with patch.object(self.checkpoints, "record") as record:
                    game._record_checkpoint()
                record.assert_not_called()
                self.assertFalse(self.checkpoints.path.exists())

    def test_checkpoint_failure_reports_problem_without_stopping_story_dispatch(self):
        ui = RecoveryUI()
        game = self.game(ui)
        game.state = self.state()
        with patch.object(self.checkpoints, "record", side_effect=OSError("disk full")), patch.object(game, "_chapter_one_decision", return_value=False) as scene:
            game._run_journey()
        scene.assert_called_once()
        self.assertIn("Checkpoint could not be saved: disk full", "\n".join(ui.output))
        self.assertEqual(ui.toasts, ["Checkpoint could not be saved: disk full"])

    def test_main_menu_can_resume_checkpoint_without_touching_manual_slots(self):
        saved = self.state("Mira", scene="north_gate")
        self.checkpoints.record(saved)
        ui = RecoveryUI(("Resume checkpoint", "Quit"))
        game = self.game(ui)
        with patch.object(game, "_run_journey") as journey:
            game.run()
        journey.assert_called_once()
        self.assertEqual(game.state.to_dict(), saved.to_dict())
        self.assertTrue(ui.menus[0][1][0].startswith("Resume checkpoint — Mira"))
        self.assertFalse(any(label.startswith("Resume checkpoint") for label in ui.menus[-1][1]))
        self.assertEqual(self.saves.all_slots(), [None, None, None])

    def test_corrupt_checkpoint_does_not_add_an_unusable_resume_option(self):
        self.checkpoints.path.write_text("damaged", encoding="utf-8")
        ui = RecoveryUI(("Quit",))
        self.game(ui).run()
        self.assertFalse(any(label.startswith("Resume checkpoint") for label in ui.menus[0][1]))

    def test_failed_resume_preserves_live_state_and_previous_manual_saves(self):
        ui = RecoveryUI()
        game = self.game(ui)
        original = self.state()
        game.state = original
        with patch.object(self.checkpoints, "resume", side_effect=ValueError("damaged checkpoint")):
            self.assertFalse(game._resume_checkpoint())
        self.assertIs(game.state, original)
        self.assertEqual(ui.pauses, 1)
        self.assertIn("Could not resume the checkpoint: damaged checkpoint", "\n".join(ui.output))

    def test_saves_panel_receives_validated_slot_details_and_corruption_flags(self):
        saved = self.state("Mira", scene="north_gate")
        saved.play_minutes = 73
        saved.character.hp = 13
        self.saves.save(2, saved)
        self.saves._path(3).write_text("damaged", encoding="utf-8")
        ui = SavePanelUI(({"action": "close"},))
        game = self.game(ui)
        original = self.state()
        game.state = original
        self.assertFalse(game._load_menu())
        kind, snapshot = ui.panels[0]
        self.assertEqual((kind, snapshot["mode"]), ("saves", "load"))
        slots = snapshot["slots"]
        self.assertEqual(slots[0], {"slot": 1, "empty": True, "corrupt": False})
        self.assertEqual((slots[1]["name"], slots[1]["play_minutes"], slots[1]["hp"], slots[1]["location"]), ("Mira", 73, 13, "Bree's North Gate"))
        self.assertEqual(slots[2], {"slot": 3, "empty": False, "corrupt": True, "name": "Damaged memory"})
        self.assertIs(game.state, original)

    def test_graphical_overwrite_keeps_existing_confirmation(self):
        self.saves.save(1, self.state("Earlier journey"))
        original_bytes = self.saves._path(1).read_bytes()
        ui = SavePanelUI(({"action": "select_slot", "slot": 1},), ("No",))
        game = self.game(ui)
        game.state = self.state("New journey")
        self.assertFalse(game._save_menu())
        self.assertEqual(self.saves._path(1).read_bytes(), original_bytes)
        self.assertEqual(ui.menus[0][0], "Overwrite save slot 1?")
        ui = SavePanelUI(({"action": "select_slot", "slot": 1},), ("Yes",))
        game = self.game(ui)
        game.state = self.state("New journey")
        self.assertTrue(game._save_menu())
        self.assertEqual(self.saves.load(1).character.name, "New journey")
        self.assertFalse(self.checkpoints.path.exists())

    def test_graphical_load_revalidates_damaged_slots_and_preserves_state(self):
        self.saves._path(1).write_text("damaged", encoding="utf-8")
        ui = SavePanelUI(({"action": "select_slot", "slot": 1},))
        game = self.game(ui)
        original = self.state()
        game.state = original
        self.assertFalse(game._load_menu())
        self.assertIs(game.state, original)
        self.assertIn("damaged", "\n".join(ui.output))

    def test_malformed_panel_slot_selections_cannot_modify_manual_saves(self):
        for slot in (True, "1", 0, 4, [], None):
            with self.subTest(slot=slot):
                ui = SavePanelUI(({"action": "select_slot", "slot": slot},))
                game = self.game(ui)
                game.state = self.state()
                self.assertFalse(game._save_menu())
                self.assertEqual(self.saves.all_slots(), [None, None, None])

    def test_graphical_inventory_preserves_healer_bonus_and_refreshes_snapshot(self):
        ui = SavePanelUI((
            {"action": "use", "item_id": "healing_herb"}, {"action": "close"},
        ))
        game = self.game(ui)
        game.state = self.state(origin=2)
        game.state.character.hp = 1
        game._inventory_menu()
        self.assertEqual(game.state.character.hp, 12)
        self.assertEqual(game.state.character.inventory["healing_herb"], 1)
        self.assertEqual(ui.panels[0][1]["hp"], 1)
        self.assertEqual(ui.panels[1][1]["hp"], 12)
        self.assertIn("recovered 11 Health", ui.toasts[0])

    def test_graphical_inventory_rejects_malformed_item_identity(self):
        ui = SavePanelUI((
            {"action": "equip", "item_id": []}, {"action": "close"},
        ))
        game = self.game(ui)
        game.state = self.state()
        before = game.state.to_dict()
        game._inventory_menu()
        self.assertEqual(game.state.to_dict(), before)


if __name__ == "__main__":
    unittest.main()
