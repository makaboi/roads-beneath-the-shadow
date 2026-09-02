import json
import tempfile
import unittest
from pathlib import Path

from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.savegame import SaveManager


class SaveManagerTests(unittest.TestCase):
    @staticmethod
    def _state_payload() -> dict:
        return GameState(Character.from_origin("Mira", ORIGINS[1])).to_dict()

    @staticmethod
    def _write_slot(root: Path, state: dict) -> SaveManager:
        (root / "slot_1.json").write_text(
            json.dumps({"saved_at": "now", "state": state}), encoding="utf-8"
        )
        return SaveManager(root)

    def test_save_load_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            saves = SaveManager(Path(temporary))
            state = GameState(Character.from_origin("Mira", ORIGINS[1]))
            state.scene = "branch_search"
            saves.save(2, state)

            loaded = saves.load(2)
            metadata = saves.slot_metadata(2)

            self.assertEqual(loaded.character.name, "Mira")
            self.assertEqual(loaded.scene, "branch_search")
            self.assertEqual(loaded.journey_id, state.journey_id)
            self.assertEqual(metadata["name"], "Mira")
            self.assertIsNone(saves.slot_metadata(1))

    def test_corrupt_slot_is_reported(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            (root / "slot_1.json").write_text("not json", encoding="utf-8")
            saves = SaveManager(root)

            self.assertTrue(saves.slot_metadata(1)["corrupt"])

    def test_rejects_unknown_save_version(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload = {
                "saved_at": "now",
                "state": {
                    "save_version": 999,
                    "character": {},
                },
            }
            (root / "slot_1.json").write_text(json.dumps(payload), encoding="utf-8")
            saves = SaveManager(root)

            with self.assertRaises(ValueError):
                saves.load(1)

    def test_migrates_version_one_save(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = GameState(Character.from_origin("Old Traveler", ORIGINS[0])).to_dict()
            state["save_version"] = 1
            state["character"].pop("tobin_trust")
            state.pop("journey_id")
            state.pop("visited")
            state.pop("completed_quests")
            state.pop("play_minutes")
            (root / "slot_1.json").write_text(
                json.dumps({"saved_at": "then", "state": state}), encoding="utf-8"
            )

            loaded = SaveManager(root).load(1)

            self.assertEqual(loaded.character.name, "Old Traveler")
            self.assertEqual(loaded.character.tobin_trust, 0)
            self.assertEqual(loaded.save_version, 2)
            self.assertEqual(loaded.visited, [])
            self.assertTrue(loaded.journey_id)

    def test_old_version_two_save_gets_a_stable_migrated_journey_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = self._state_payload()
            state.pop("journey_id")
            saves = self._write_slot(root, state)

            first = saves.load(1)
            second = saves.load(1)

            self.assertEqual(first.journey_id, second.journey_id)
            self.assertEqual(len(first.journey_id), 32)

    def test_rejects_malformed_character_and_state_field_types(self) -> None:
        cases = {
            "character object": ("character", []),
            "character name": ("character.name", 42),
            "flags object": ("flags", []),
            "flag value": ("flags.test", "yes"),
            "quests list": ("quests", {}),
            "journal entry": ("journal.0", 9),
            "chapter integer": ("chapter", "1"),
            "play minutes integer": ("play_minutes", 1.5),
            "missing current character field": ("character.tobin_trust", None),
        }
        for label, (field, bad_value) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                state = self._state_payload()
                if field == "character":
                    state["character"] = bad_value
                elif field.startswith("character."):
                    character_field = field.split(".", 1)[1]
                    if label.startswith("missing"):
                        state["character"].pop(character_field)
                    else:
                        state["character"][character_field] = bad_value
                elif field.startswith("flags."):
                    state["flags"][field.split(".", 1)[1]] = bad_value
                elif field == "journal.0":
                    state["journal"] = [bad_value]
                else:
                    state[field] = bad_value
                saves = self._write_slot(Path(temporary), state)

                with self.assertRaisesRegex(ValueError, "must be|missing required"):
                    saves.load(1)

    def test_rejects_invalid_health_and_focus_ranges(self) -> None:
        cases = {
            "nonpositive max HP": ("max_hp", 0),
            "HP below zero": ("hp", -1),
            "HP above maximum": ("hp", 999),
            "nonpositive max focus": ("max_focus", 0),
            "focus below zero": ("focus", -1),
            "focus above maximum": ("focus", 999),
        }
        for label, (field, bad_value) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                state = self._state_payload()
                state["character"][field] = bad_value
                saves = self._write_slot(Path(temporary), state)

                with self.assertRaisesRegex(ValueError, f"character.{field}"):
                    saves.load(1)

    def test_rejects_unknown_items_invalid_quantities_and_bad_equipment(self) -> None:
        cases = {
            "unknown inventory item": {"inventory": {"not_a_real_item": 1}},
            "zero quantity": {"inventory": {"hunting_knife": 0}},
            "string quantity": {"inventory": {"hunting_knife": "1"}},
            "unknown equipped weapon": {"weapon": "not_a_real_item"},
            "equipped item absent": {"inventory": {}, "weapon": "hunting_knife"},
            "armor in weapon slot": {"weapon": "patched_leather"},
        }
        for label, changes in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                state = self._state_payload()
                state["character"].update(changes)
                saves = self._write_slot(Path(temporary), state)

                with self.assertRaises(ValueError):
                    saves.load(1)

    def test_rejects_unknown_ending_and_invalid_journey_id(self) -> None:
        cases = {
            "unknown ending": ("ending", "the_moon_wins"),
            "null journey ID": ("journey_id", None),
            "empty journey ID": ("journey_id", ""),
            "oversized journey ID": ("journey_id", "x" * 129),
        }
        for label, (field, bad_value) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                state = self._state_payload()
                state[field] = bad_value
                saves = self._write_slot(Path(temporary), state)

                with self.assertRaises(ValueError):
                    saves.load(1)

    def test_metadata_marks_semantically_invalid_save_corrupt(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            state = self._state_payload()
            state["character"]["inventory"]["forged_relic"] = 1
            saves = self._write_slot(root, state)

            self.assertEqual(saves.slot_metadata(1), {"slot": 1, "corrupt": True})

    def test_save_refuses_to_write_an_invalid_in_memory_state(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            saves = SaveManager(Path(temporary))
            state = GameState(Character.from_origin("Mira", ORIGINS[0]))
            state.character.hp = state.character.max_hp + 1

            with self.assertRaisesRegex(ValueError, "character.hp"):
                saves.save(1, state)
            self.assertFalse((Path(temporary) / "slot_1.json").exists())

    def test_rejects_terminal_and_unicode_control_characters_in_loaded_text(self) -> None:
        cases = {
            "name escape": lambda state: state["character"].__setitem__("name", "Mira\x1b[31m"),
            "journal newline": lambda state: state.__setitem__("journal", ["A forged clue\nsecond line"]),
            "quest bidi control": lambda state: state.__setitem__("quests", ["Find \u202ethe false road"]),
            "journey tab": lambda state: state.__setitem__("journey_id", "journey\tspoof"),
            "scene carriage return": lambda state: state.__setitem__("scene", "wayhouse\r"),
        }
        for label, corrupt in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                state = self._state_payload()
                corrupt(state)
                saves = self._write_slot(Path(temporary), state)

                with self.assertRaisesRegex(ValueError, "control or non-printing"):
                    saves.load(1)
                self.assertEqual(saves.slot_metadata(1), {"slot": 1, "corrupt": True})

    def test_rejects_unknown_scenes_and_inconsistent_ending_state(self) -> None:
        cases = {
            "unknown scene": ("somewhere_impossible", None, "Unknown scene"),
            "complete without ending": ("complete", None, "if and only if"),
            "ending during active scene": ("wayhouse", "fellowship", "if and only if"),
        }
        for label, (scene, ending, message) in cases.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as temporary:
                state = self._state_payload()
                state["scene"] = scene
                state["ending"] = ending
                saves = self._write_slot(Path(temporary), state)

                with self.assertRaisesRegex(ValueError, message):
                    saves.load(1)

    def test_accepts_active_and_completed_scene_ending_pairs(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            active = self._state_payload()
            active["scene"] = "wayhouse"
            active["ending"] = None
            saves = self._write_slot(root, active)
            self.assertEqual(saves.load(1).scene, "wayhouse")

            completed = self._state_payload()
            completed["scene"] = "complete"
            completed["ending"] = "fellowship"
            saves = self._write_slot(root, completed)
            loaded = saves.load(1)
            self.assertEqual((loaded.scene, loaded.ending), ("complete", "fellowship"))

    def test_accepts_active_part_two_scene_at_chapter_two(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            saves = SaveManager(Path(temporary))
            state = GameState(Character.from_origin("Mira", ORIGINS[0]))
            state.chapter = 2
            state.scene = "part2_last_seal"

            saves.save(1, state)

            loaded = saves.load(1)
            self.assertEqual((loaded.chapter, loaded.scene), (2, "part2_last_seal"))

    def test_accepts_completed_living_road_ending(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            saves = SaveManager(Path(temporary))
            state = GameState(Character.from_origin("Mira", ORIGINS[0]))
            state.chapter = 2
            state.scene = "complete"
            state.ending = "living_road"

            saves.save(1, state)

            loaded = saves.load(1)
            self.assertEqual((loaded.scene, loaded.ending), ("complete", "living_road"))

    def test_rejects_part_two_scene_at_chapter_one(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            saves = SaveManager(Path(temporary))
            state = GameState(Character.from_origin("Mira", ORIGINS[0]))
            state.scene = "part2_last_seal"

            with self.assertRaisesRegex(ValueError, "Part II scenes require chapter 2"):
                saves.save(1, state)


if __name__ == "__main__":
    unittest.main()
