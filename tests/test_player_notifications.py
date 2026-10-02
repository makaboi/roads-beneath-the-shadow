"""Storage failures are visible while the player's existing records survive."""

from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.profile import ProfileManager
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.ui import TerminalUI


class RecordNotificationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.output = []
        self.ui = TerminalUI(color=False, fast=True, input_fn=lambda _: "2", output_fn=self.output.append)
        self.profile = ProfileManager(self.root / "profile.json")
        self.game = Game(self.ui, saves=SaveManager(self.root / "saves"), profile=self.profile)
        self.game.state = GameState(Character.from_origin("Mira", ORIGINS[0]), scene="complete", ending="hidden_road")

    def tearDown(self):
        self.temp.cleanup()

    def test_viewing_a_damaged_chronicle_explains_the_empty_view_without_overwriting(self):
        damaged = b"{ earlier Chronicle"
        self.profile.path.write_bytes(damaged)
        panels = []
        self.ui.show_panel = lambda kind, data: panels.append((kind, data))
        self.game._show_chronicle()
        self.assertEqual(self.profile.path.read_bytes(), damaged)
        self.assertEqual(panels[0][0], "chronicle")
        self.assertIn("existing file has been kept", panels[0][1]["notice"])
        self.assertEqual(self.profile.load().completed_runs, 0)

    def test_recovered_completion_names_the_exact_backup_in_the_ending(self):
        damaged = b"{ earlier Chronicle"
        self.profile.path.write_bytes(damaged)
        self.game._show_ending()
        backup = self.profile.last_recovery_backup
        self.assertIsNotNone(backup)
        self.assertEqual(backup.read_bytes(), damaged)
        self.assertIn(backup.name, " ".join(self.output))
        self.assertEqual(self.profile.load().completed_runs, 1)

    def test_failed_completion_record_does_not_claim_credit_and_offers_manual_save(self):
        with patch.object(self.profile, "record", side_effect=PermissionError("Read-only record")):
            self.game._show_ending()
        self.assertFalse(self.game.state.flags.get("profile_recorded_part_1", False))
        self.assertIn("Chronicle could not be saved", " ".join(self.output))
        self.assertIn("manual slot", " ".join(self.output))
