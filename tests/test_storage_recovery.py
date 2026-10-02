"""Damaged records stay reviewable and cannot crash the saves or Chronicle menus."""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.profile import PlayerProfile, ProfileManager
from roads_beneath_shadow.savegame import SaveManager


class StorageRecoveryTests(unittest.TestCase):
    @staticmethod
    def completed_state():
        return GameState(Character.from_origin("Arin", ORIGINS[0]), scene="complete", ending="fellowship")

    def test_deeply_nested_manual_slot_is_damaged_and_other_slots_still_load(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            saves = SaveManager(root)
            saves.save(2, self.completed_state())
            damaged = b'{"state":' + b'[' * 15_000 + b'0' + b']' * 15_000 + b'}'
            (root / "slot_1.json").write_bytes(damaged)
            with self.assertRaisesRegex(ValueError, "too deeply nested"):
                saves.load(1)
            metadata = saves.all_slots()
            self.assertTrue(metadata[0]["corrupt"])
            self.assertEqual(metadata[1]["name"], "Arin")
            self.assertEqual((root / "slot_1.json").read_bytes(), damaged)
            self.assertEqual(saves.load(2).ending, "fellowship")

    def test_damaged_profile_view_is_read_only_and_new_ending_keeps_exact_backup(self):
        damaged_records = (
            b'not JSON\n',
            b'\xffinvalid UTF-8',
            b'[' * 15_000 + b'0' + b']' * 15_000,
            json.dumps({"completed_runs": float("inf")}).encode(),
            json.dumps({"endings": {"fellowship": float("inf")}}).encode(),
            json.dumps({"completed_runs": True}).encode(),
            json.dumps({"completed_runs": 1.5}).encode(),
            json.dumps({"endings": {"fellowship": False}}).encode(),
            json.dumps({"endings": {"fellowship": 2.5}}).encode(),
            json.dumps({"endings": ["fellowship", 2]}).encode(),
            json.dumps({"origins_completed": "bree_wayfarer"}).encode(),
            json.dumps({"achievements": {"part_one": True}}).encode(),
            json.dumps({"recorded_journeys": "record-id"}).encode(),
            json.dumps({"recorded_journeys": [{"id": "record-id"}]}).encode(),
            b'[]',
        )
        for damaged in damaged_records:
            with self.subTest(damaged=damaged[:40]), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "profile.json"
                path.write_bytes(damaged)
                manager = ProfileManager(path)
                self.assertEqual(manager.load(), PlayerProfile())
                self.assertTrue(manager.last_load_error)
                self.assertEqual(path.read_bytes(), damaged)
                self.assertEqual(list(path.parent.iterdir()), [path])

                manager.record(self.completed_state())
                backup = manager.last_recovery_backup
                self.assertIsNotNone(backup)
                self.assertNotEqual(backup, path)
                self.assertEqual(backup.read_bytes(), damaged)
                self.assertEqual(manager.load().completed_runs, 1)
                self.assertIsNone(manager.last_load_error)
                self.assertEqual(manager.load().endings, {"fellowship": 1})

    def test_valid_legacy_profile_loads_without_a_recovery_or_loss_of_progress(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            legacy = json.dumps({
                "completed_runs": 2,
                "endings": {"fellowship": 2},
                "origins_completed": ["bree_wayfarer"],
                "achievements": ["part_one"],
            }).encode()
            path.write_bytes(legacy)
            manager = ProfileManager(path)

            loaded = manager.load()

            self.assertEqual((loaded.completed_runs, loaded.endings), (2, {"fellowship": 2}))
            self.assertIsNone(manager.last_load_error)
            self.assertEqual(path.read_bytes(), legacy)
            self.assertEqual(list(path.parent.iterdir()), [path])
            manager.record(self.completed_state())
            self.assertIsNone(manager.last_recovery_backup)
            self.assertEqual(manager.load().completed_runs, 3)

    def test_read_permission_error_does_not_backup_or_overwrite_profile(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            original = b'{"completed_runs": 7}'
            path.write_bytes(original)
            manager = ProfileManager(path)
            original_open = Path.open

            def deny_record_reads(file, *args, **kwargs):
                mode = args[0] if args else kwargs.get("mode", "r")
                if file == path and "r" in mode:
                    raise PermissionError("Cannot read this record")
                return original_open(file, *args, **kwargs)

            with patch.object(Path, "open", new=deny_record_reads):
                self.assertEqual(manager.load().completed_runs, 0)
                self.assertIn("Cannot read", manager.last_load_error)
                with self.assertRaises(PermissionError):
                    manager.record(self.completed_state())
            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(list(path.parent.iterdir()), [path])
            self.assertIsNone(manager.last_recovery_backup)

    def test_failed_replacement_keeps_original_damaged_file_and_recovery_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            damaged = b'original damaged record\n'
            path.write_bytes(damaged)
            manager = ProfileManager(path)
            with patch("roads_beneath_shadow.profile.os.replace", side_effect=OSError("Disk is full")):
                with self.assertRaises(OSError):
                    manager.record(self.completed_state())
            self.assertEqual(path.read_bytes(), damaged)
            self.assertEqual(manager.last_recovery_backup.read_bytes(), damaged)
            self.assertFalse(list(path.parent.glob("*.tmp")))

    def test_repeated_recovery_never_overwrites_an_earlier_damaged_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            manager = ProfileManager(path)
            copies = []
            for damaged in (b'first bad record', b'second bad record'):
                path.write_bytes(damaged)
                manager.record(self.completed_state())
                copies.append(manager.last_recovery_backup)
            self.assertNotEqual(copies[0], copies[1])
            self.assertEqual([backup.read_bytes() for backup in copies], [b'first bad record', b'second bad record'])

    def test_episode_mismatches_are_damaged_and_cannot_replace_a_valid_save(self):
        for scene, chapter, ending in (
            ("chapter1_intro", 2, None),
            ("complete", 2, "fellowship"),
            ("complete", 1, "living_road"),
            ("part2_hall", 1, None),
        ):
            with self.subTest(scene=scene, chapter=chapter, ending=ending), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                saves = SaveManager(root)
                saves.save(1, self.completed_state())
                original = (root / "slot_1.json").read_bytes()
                invalid = GameState(Character.from_origin("Arin", ORIGINS[0]), scene=scene, chapter=chapter, ending=ending)
                with self.assertRaisesRegex(ValueError, "require chapter"):
                    saves.save(1, invalid)
                self.assertEqual((root / "slot_1.json").read_bytes(), original)

                (root / "slot_2.json").write_text(json.dumps({"state": invalid.to_dict()}), encoding="utf-8")
                self.assertTrue(saves.slot_metadata(2)["corrupt"])
                self.assertEqual(saves.load(1).ending, "fellowship")


if __name__ == "__main__":
    unittest.main()
