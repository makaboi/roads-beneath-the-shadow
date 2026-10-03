"""Chronicle write limits preserve earlier completions and ending recovery."""

import json
import os
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.profile import PlayerProfile, ProfileManager
from roads_beneath_shadow.savegame import MAX_SAVE_BYTES, SaveManager
from roads_beneath_shadow.ui import TerminalUI


class ProfileSizeBoundaryTests(unittest.TestCase):
    @staticmethod
    def profile_with_count(count):
        return PlayerProfile(
            completed_runs=count,
            endings={"fellowship": count},
            origins_completed=[ORIGINS[0].origin_id],
            achievements=["part_one", "unbroken_hope"],
            recorded_journeys=[f"{index:032x}:part_1" for index in range(count)],
        )

    @staticmethod
    def encoded_bytes(profile):
        # The writer uses text mode with default newline translation. Windows
        # writes CRLF, so the fixture must measure those bytes too.
        text = json.dumps(asdict(profile), ensure_ascii=False, indent=2) + "\n"
        return text.replace("\n", os.linesep).encode("utf-8")

    @classmethod
    def setUpClass(cls):
        # Find the largest history of ordinary generated IDs that reloads,
        # without padding, malformed fields, or unusual journey-ID lengths.
        low, high = 0, 50_000
        while low < high:
            middle = (low + high + 1) // 2
            if len(cls.encoded_bytes(cls.profile_with_count(middle))) <= MAX_SAVE_BYTES:
                low = middle
            else:
                high = middle - 1
        cls.near_limit_count = low

    @classmethod
    def near_limit_profile(cls):
        return cls.profile_with_count(cls.near_limit_count)

    @classmethod
    def unicode_boundary_profile(cls, extra_bytes=0):
        profile = cls.near_limit_profile()
        remaining = MAX_SAVE_BYTES + extra_bytes - len(cls.encoded_bytes(profile))
        # Each ASCII-to-é substitution adds one UTF-8 byte while keeping each
        # valid 32-character journey ID the same length. Two keys cover CRLF
        # as well as LF budgets without making the records duplicate.
        for index in range(2):
            replaced = min(32, remaining)
            profile.recorded_journeys[index] = "é" * replaced + profile.recorded_journeys[index][replaced:]
            remaining -= replaced
        assert remaining == 0
        return profile

    @staticmethod
    def completed_state():
        state = GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            scene="complete",
            ending="fellowship",
        )
        state.character.hope = 3
        return state

    def test_ordinary_record_crossing_limit_keeps_readable_chronicle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            manager = ProfileManager(path)
            earlier = self.near_limit_profile()
            manager.save(earlier)
            original = path.read_bytes()
            self.assertGreater(len(original), MAX_SAVE_BYTES - 50)
            self.assertLessEqual(len(original), MAX_SAVE_BYTES)

            with self.assertRaisesRegex(ValueError, "existing Chronicle has been kept"):
                manager.record(self.completed_state())

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(manager.load(), earlier)
            self.assertIsNone(manager.last_load_error)
            self.assertIsNone(manager.last_recovery_backup)
            self.assertFalse(list(path.parent.glob("*.tmp")))

    def test_exact_byte_limit_with_unicode_round_trips_every_record(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            manager = ProfileManager(path)
            profile = self.unicode_boundary_profile()
            self.assertEqual(len(self.encoded_bytes(profile)), MAX_SAVE_BYTES)

            manager.save(profile)

            self.assertEqual(path.stat().st_size, MAX_SAVE_BYTES)
            self.assertEqual(manager.load(), profile)
            self.assertIsNone(manager.last_load_error)
            self.assertFalse(list(path.parent.glob("*.tmp")))

    def test_unicode_candidate_one_byte_over_limit_keeps_original(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "profile.json"
            manager = ProfileManager(path)
            earlier = PlayerProfile(completed_runs=1, endings={"fellowship": 1})
            manager.save(earlier)
            original = path.read_bytes()
            profile = self.unicode_boundary_profile(extra_bytes=1)
            self.assertEqual(len(self.encoded_bytes(profile)), MAX_SAVE_BYTES + 1)

            with self.assertRaisesRegex(ValueError, "existing Chronicle has been kept"):
                manager.save(profile)

            self.assertEqual(path.read_bytes(), original)
            self.assertEqual(manager.load(), earlier)
            self.assertFalse(list(path.parent.glob("*.tmp")))

    def test_ending_can_manually_save_when_chronicle_is_at_capacity(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            manager = ProfileManager(root / "profile.json")
            earlier = self.near_limit_profile()
            manager.save(earlier)
            original = manager.path.read_bytes()
            output = []
            answers = iter(("1", "1"))  # Ending -> Save this journey -> slot 1.
            game = Game(
                TerminalUI(
                    color=False,
                    fast=True,
                    input_fn=lambda _prompt: next(answers),
                    output_fn=output.append,
                ),
                profile=manager,
                saves=SaveManager(root / "saves"),
            )
            game.state = self.completed_state()

            game._show_ending()

            self.assertEqual(manager.path.read_bytes(), original)
            self.assertEqual(manager.load(), earlier)
            self.assertFalse(game.state.flags.get("profile_recorded_part_1"))
            saved = game.saves.load(1)
            self.assertEqual(saved.to_dict(), game.state.to_dict())
            self.assertFalse(saved.flags.get("profile_recorded_part_1"))
            transcript = "\n".join(output)
            self.assertIn("The Chronicle could not be saved", transcript)
            self.assertIn("You can still save this journey in a manual slot", transcript)
            self.assertIn("Journey saved in slot 1", transcript)
            self.assertFalse(list(root.glob("*.tmp")))


if __name__ == "__main__":
    unittest.main()
