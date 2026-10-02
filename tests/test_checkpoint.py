"""Automatic checkpoints must preserve manual slots and recover atomically."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from roads_beneath_shadow.checkpoint import CheckpointManager
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.savegame import MAX_SAVE_BYTES, SaveManager


class CheckpointManagerTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.checkpoints = CheckpointManager(self.root)

    @staticmethod
    def state():
        state = GameState(Character.from_origin("Mira", ORIGINS[1]), scene="north_gate", play_minutes=19)
        state.flags.update({"lesson_tracking": True, "found_ranger_cipher": True})
        state.character.hp -= 3
        state.character.hope = 2
        state.character.mara_trust = 4
        state.character.tobin_trust = 1
        state.character.add_item("silver_star")
        state.add_quest("Find Calenor's road")
        state.add_journal("The watchman's lantern was broken.")
        state.visited.append("Bree")
        state.completed_quests.append("Read the letter")
        return state

    def write_payload(self, state):
        self.checkpoints.path.write_text(json.dumps({"saved_at": "then", "state": state}), encoding="utf-8")

    def test_round_trip_preserves_the_complete_original_state(self):
        state = self.state()
        destination = self.checkpoints.record(state)
        self.assertEqual(destination, self.root / "checkpoint.json")
        self.assertEqual(self.checkpoints.resume().to_dict(), state.to_dict())
        metadata = self.checkpoints.metadata()
        self.assertEqual(metadata["name"], "Mira")
        self.assertEqual(metadata["scene"], "north_gate")
        self.assertEqual(metadata["chapter"], 1)
        self.assertNotIn("slot", metadata)
        payload = json.loads(destination.read_text(encoding="utf-8"))
        self.assertEqual(set(payload), {"saved_at", "state"})
        self.assertEqual(payload["state"]["save_version"], 2)

    def test_record_and_clear_never_modify_any_manual_slot(self):
        saves = SaveManager(self.root)
        for slot in range(1, 4):
            state = self.state()
            state.character.name = f"Traveler {slot}"
            saves.save(slot, state)
        before = {slot: saves._path(slot).read_bytes() for slot in range(1, 4)}
        self.checkpoints.record(self.state())
        self.checkpoints.clear()
        for slot in range(1, 4):
            self.assertEqual(saves._path(slot).read_bytes(), before[slot])
        self.assertFalse(self.checkpoints.path.exists())
        with self.assertRaises(ValueError):
            self.checkpoints.save(2, self.state())

    def test_identical_serialized_state_does_not_rewrite_or_change_timestamp(self):
        state = self.state()
        self.checkpoints.record(state)
        before = self.checkpoints.path.read_bytes()
        with patch.object(SaveManager, "save", wraps=SaveManager.save) as save:
            self.checkpoints.record(GameState.from_dict(state.to_dict()))
        save.assert_not_called()
        self.assertEqual(self.checkpoints.path.read_bytes(), before)

    def test_identical_existing_state_is_not_rewritten_after_restart(self):
        state = self.state()
        self.checkpoints.record(state)
        restarted = CheckpointManager(self.root)
        with patch.object(SaveManager, "save") as save:
            restarted.record(state)
        save.assert_not_called()

    def test_every_actual_state_change_can_update_the_checkpoint(self):
        state = self.state()
        self.checkpoints.record(state)
        changes = (
            lambda: setattr(state, "scene", "road_from_bree"),
            lambda: setattr(state.character, "hp", state.character.hp - 1),
            lambda: state.flags.__setitem__("rescued_watchman", True),
            lambda: state.add_journal("A new trail sign points east."),
            lambda: state.add_quest("Keep the watch safe"),
            lambda: setattr(state, "play_minutes", state.play_minutes + 1),
        )
        for change in changes:
            before = self.checkpoints.path.read_bytes()
            change()
            self.checkpoints.record(state)
            self.assertNotEqual(self.checkpoints.path.read_bytes(), before)
            self.assertEqual(self.checkpoints.resume().to_dict(), state.to_dict())

    def test_external_deletion_or_corruption_cannot_suppress_a_needed_write(self):
        state = self.state()
        self.checkpoints.record(state)
        self.checkpoints.path.unlink()
        self.checkpoints.record(state)
        self.assertEqual(self.checkpoints.resume().to_dict(), state.to_dict())
        self.checkpoints.path.write_text("broken", encoding="utf-8")
        self.checkpoints.record(state)
        self.assertEqual(self.checkpoints.resume().to_dict(), state.to_dict())

    def test_missing_checkpoint_is_safe_for_the_main_menu(self):
        self.assertIsNone(self.checkpoints.metadata())
        with self.assertRaises(FileNotFoundError):
            self.checkpoints.resume()
        self.checkpoints.clear()
        self.assertIsNone(self.checkpoints.metadata())

    def test_malformed_or_semantically_invalid_checkpoint_is_reported_safely(self):
        cases = (
            "not JSON",
            "[]",
            json.dumps({"state": []}),
            json.dumps({"state": {"save_version": 999, "character": {}}}),
            "[" * 2000 + "]" * 2000,
        )
        for contents in cases:
            with self.subTest(contents=contents):
                self.checkpoints.path.write_text(contents, encoding="utf-8")
                self.assertEqual(self.checkpoints.metadata(), {"corrupt": True})
                with self.assertRaises((ValueError, TypeError, RecursionError)):
                    self.checkpoints.resume()
        invalid = self.state().to_dict()
        invalid["character"]["hp"] = 500
        self.write_payload(invalid)
        self.assertEqual(self.checkpoints.metadata(), {"corrupt": True})
        with self.assertRaisesRegex(ValueError, "character.hp"):
            self.checkpoints.resume()

    def test_unreadable_and_oversized_checkpoint_cannot_block_menu_metadata(self):
        self.checkpoints.record(self.state())
        with patch.object(SaveManager, "slot_metadata", side_effect=PermissionError("unreadable")):
            self.assertEqual(self.checkpoints.metadata(), {"corrupt": True})
        self.checkpoints.path.write_bytes(b" " * (MAX_SAVE_BYTES + 1))
        self.assertEqual(self.checkpoints.metadata(), {"corrupt": True})
        with self.assertRaisesRegex(ValueError, "too large"):
            self.checkpoints.resume()

    def test_version_one_migration_uses_the_existing_save_rules(self):
        legacy = self.state().to_dict()
        legacy["save_version"] = 1
        legacy["character"].pop("tobin_trust")
        for field in ("journey_id", "visited", "completed_quests", "play_minutes"):
            legacy.pop(field)
        self.write_payload(legacy)
        loaded = self.checkpoints.resume()
        self.assertEqual(loaded.save_version, 2)
        self.assertEqual(loaded.character.tobin_trust, 0)
        self.assertEqual(loaded.visited, [])
        self.assertEqual(loaded.journey_id, CheckpointManager(self.root).resume().journey_id)

    def test_older_version_two_save_gets_a_stable_journey_identity(self):
        legacy = self.state().to_dict()
        legacy.pop("journey_id")
        self.write_payload(legacy)
        first = self.checkpoints.resume()
        second = self.checkpoints.resume()
        self.assertEqual(first.journey_id, second.journey_id)
        self.assertEqual(len(first.journey_id), 32)

    def test_record_normalizes_a_legacy_in_memory_state_to_version_two(self):
        legacy = self.state()
        legacy.save_version = 1
        self.checkpoints.record(legacy)
        payload = json.loads(self.checkpoints.path.read_text(encoding="utf-8"))
        self.assertEqual(payload["state"]["save_version"], 2)
        self.assertEqual(legacy.save_version, 1)

    def test_failed_atomic_replace_preserves_old_checkpoint_and_allows_retry(self):
        state = self.state()
        self.checkpoints.record(state)
        before = self.checkpoints.path.read_bytes()
        state.scene = "road_from_bree"
        with patch("roads_beneath_shadow.savegame.os.replace", side_effect=OSError("disk full")):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.checkpoints.record(state)
        self.assertEqual(self.checkpoints.path.read_bytes(), before)
        self.assertFalse(list(self.root.glob("*.tmp")))
        self.checkpoints.record(state)
        self.assertEqual(self.checkpoints.resume().scene, "road_from_bree")

    def test_failed_temporary_write_preserves_old_checkpoint(self):
        state = self.state()
        self.checkpoints.record(state)
        before = self.checkpoints.path.read_bytes()
        state.character.hp -= 1
        with patch("roads_beneath_shadow.savegame.json.dump", side_effect=OSError("write failed")):
            with self.assertRaisesRegex(OSError, "write failed"):
                self.checkpoints.record(state)
        self.assertEqual(self.checkpoints.path.read_bytes(), before)
        self.assertFalse(list(self.root.glob("*.tmp")))

    def test_invalid_in_memory_state_is_rejected_before_replacing_checkpoint(self):
        state = self.state()
        self.checkpoints.record(state)
        before = self.checkpoints.path.read_bytes()
        state.scene = "unknown_place"
        with self.assertRaisesRegex(ValueError, "Unknown scene"):
            self.checkpoints.record(state)
        self.assertEqual(self.checkpoints.path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
