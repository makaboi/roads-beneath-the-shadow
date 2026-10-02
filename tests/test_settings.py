import json
import tempfile
import unittest
from pathlib import Path

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.combat import CombatDifficulty
from roads_beneath_shadow.settings import SettingsManager, UserSettings
from roads_beneath_shadow.ui import TerminalUI


class SettingsManagerTests(unittest.TestCase):
    def test_preferences_round_trip(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = SettingsManager(Path(temporary) / "settings.json")
            expected = UserSettings(
                color_mode="off",
                sound=True,
                text_speed="fast",
                reduced_motion=True,
                screen_reader=True,
                difficulty="story",
                autosave=False,
                music_volume=0.5,
                sfx_volume=0.75,
                text_size="larger",
            )

            manager.save(expected)
            loaded = manager.load()

            self.assertEqual(loaded, expected)

    def test_missing_or_damaged_settings_use_safe_defaults(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            manager = SettingsManager(path)
            self.assertEqual(manager.load(), UserSettings())

            path.write_text("not json", encoding="utf-8")
            self.assertEqual(manager.load(), UserSettings())

    def test_unknown_values_are_repaired_and_extra_keys_ignored(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text(
                json.dumps(
                    {
                        "color_mode": "neon",
                        "text_speed": "warp",
                        "difficulty": "impossible",
                        "sound": "yes",
                        "reduced_motion": 1,
                        "future_option": True,
                    }
                ),
                encoding="utf-8",
            )

            loaded = SettingsManager(path).load()

            self.assertEqual(loaded.color_mode, "auto")
            self.assertEqual(loaded.text_speed, "normal")
            self.assertEqual(loaded.difficulty, "ranger")
            self.assertFalse(loaded.sound)
            self.assertFalse(loaded.reduced_motion)

    def test_unreadable_or_excessively_nested_settings_do_not_prevent_launch(self) -> None:
        from unittest import mock
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            manager = SettingsManager(path)
            path.write_text("[" * 2500 + "0" + "]" * 2500, encoding="utf-8")
            self.assertEqual(manager.load(), UserSettings())
            with mock.patch.object(Path, "exists", side_effect=PermissionError("Unavailable preferences")):
                self.assertEqual(manager.load(), UserSettings())

    def test_old_preferences_gain_safe_audio_and_checkpoint_defaults(self) -> None:
        settings = UserSettings.from_dict({"sound": True, "difficulty": "shadow"})
        self.assertTrue(settings.autosave)
        self.assertEqual((settings.music_volume, settings.sfx_volume), (0.25, 0.6))
        self.assertTrue(settings.sound)
        self.assertEqual(settings.difficulty, "shadow")
        self.assertEqual(settings.text_size, "standard")

    def test_text_size_is_optional_in_existing_version_one_settings(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "settings.json"
            path.write_text(json.dumps({"version": 1, "text_speed": "slow", "reduced_motion": True, "sound": False}), encoding="utf-8")
            settings = SettingsManager(path).load()
            self.assertEqual(settings.text_size, "standard")
            self.assertEqual(settings.text_speed, "slow")
            self.assertTrue(settings.reduced_motion)
            self.assertEqual(settings.version, 1)

    def test_each_text_size_persists_independently_of_other_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = SettingsManager(Path(temporary) / "settings.json")
            for size in ("standard", "large", "larger"):
                with self.subTest(size=size):
                    settings = UserSettings(text_size=size, music_volume=0, reduced_motion=True)
                    manager.save(settings)
                    self.assertEqual(manager.load(), settings)
                    self.assertEqual(json.loads(manager.path.read_text())["text_size"], size)

    def test_invalid_text_sizes_restore_readable_default_without_resetting_settings(self) -> None:
        for invalid in (None, True, 23, "giant", "Large", [], {}):
            with self.subTest(invalid=invalid):
                settings = UserSettings.from_dict({"text_size": invalid, "text_speed": "fast", "difficulty": "story"})
                self.assertEqual(settings.text_size, "standard")
                self.assertEqual(settings.text_speed, "fast")
                self.assertEqual(settings.difficulty, "story")

    def test_invalid_volume_and_checkpoint_preferences_use_safe_defaults(self) -> None:
        for invalid in (True, "loud", -0.5, 1.1, float("nan"), float("inf"), 10 ** 1000):
            with self.subTest(invalid=invalid):
                settings = UserSettings.from_dict({"music_volume": invalid, "sfx_volume": invalid, "autosave": "yes"})
                self.assertEqual((settings.music_volume, settings.sfx_volume), (0.25, 0.6))
                self.assertTrue(settings.autosave)
        self.assertEqual(UserSettings.from_dict({"music_volume": 0, "sfx_volume": 1}).music_volume, 0.0)
        self.assertEqual(UserSettings.from_dict({"music_volume": 0, "sfx_volume": 1}).sfx_volume, 1.0)

    def test_graphical_settings_apply_audio_volumes_and_checkpoint_preference(self) -> None:
        class GraphicalSettingsUI(TerminalUI):
            supports_checkpoints = True

        with tempfile.TemporaryDirectory() as temporary:
            manager = SettingsManager(Path(temporary) / "settings.json")
            choices = iter(["7", "8", "9", "11"])
            ui = GraphicalSettingsUI(color=False, fast=True, input_fn=lambda _: next(choices), output_fn=lambda _: None)
            game = Game(ui, settings_manager=manager, user_settings=UserSettings(music_volume=0.25, sfx_volume=0.6))
            self.assertEqual((ui.music_volume, ui.sfx_volume), (0.25, 0.6))
            game._settings()
            loaded = manager.load()
            self.assertEqual((loaded.music_volume, loaded.sfx_volume), (0.5, 0.75))
            self.assertEqual((ui.music_volume, ui.sfx_volume), (0.5, 0.75))
            self.assertFalse(loaded.autosave)

    def test_graphical_volume_controls_can_mute_without_enabling_sound(self) -> None:
        class GraphicalSettingsUI(TerminalUI):
            supports_checkpoints = True

        choices = iter(["7", "8", "11"])
        ui = GraphicalSettingsUI(color=False, fast=True, input_fn=lambda _: next(choices), output_fn=lambda _: None)
        game = Game(ui, user_settings=UserSettings(music_volume=1.0, sfx_volume=1.0))
        game._settings()
        self.assertEqual((ui.music_volume, ui.sfx_volume), (0.0, 0.0))
        self.assertFalse(ui.sound_enabled)

    def test_graphical_reading_size_cycles_and_persists_without_changing_audio(self) -> None:
        class GraphicalSettingsUI(TerminalUI):
            supports_checkpoints = True

        with tempfile.TemporaryDirectory() as temporary:
            manager = SettingsManager(Path(temporary) / "settings.json")
            choices = iter(["10", "10", "11"])
            ui = GraphicalSettingsUI(color=False, fast=True, input_fn=lambda _: next(choices), output_fn=lambda _: None)
            game = Game(ui, settings_manager=manager, user_settings=UserSettings())
            game._settings()
            self.assertEqual(ui.text_size, "larger")
            self.assertEqual(manager.load().text_size, "larger")
            self.assertEqual((ui.music_volume, ui.sfx_volume), (0.25, 0.6))
            self.assertFalse(ui.sound_enabled)

    def test_game_settings_menu_applies_and_persists_player_preferences(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            manager = SettingsManager(Path(temporary) / "settings.json")
            settings = UserSettings(color_mode="off")
            choices = iter(["1", "3", "4", "5", "6", "7"])
            ui = TerminalUI(
                color=False,
                fast=True,
                input_fn=lambda _: next(choices),
                output_fn=lambda _: None,
                sound_fn=lambda _: True,
            )
            game = Game(ui, settings_manager=manager, user_settings=settings)

            game._settings()

            loaded = manager.load()
            self.assertTrue(loaded.sound)
            self.assertEqual(loaded.text_speed, "fast")
            self.assertTrue(loaded.reduced_motion)
            self.assertTrue(loaded.screen_reader)
            self.assertEqual(loaded.difficulty, "shadow")
            self.assertEqual(game.combat.default_difficulty, CombatDifficulty.HARD)


if __name__ == "__main__":
    unittest.main()
