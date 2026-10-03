"""Graphical color choices visibly toggle while terminal detection remains available."""

import tempfile
import unittest
from pathlib import Path

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.settings import SettingsManager, UserSettings
from roads_beneath_shadow.ui import TerminalUI


class DetectedColorUI(TerminalUI):
    @staticmethod
    def _supports_color():
        return True


class GraphicalColorUI(DetectedColorUI):
    supports_graphical_settings = True


class GraphicalColorSettingsTests(unittest.TestCase):
    def settings_session(self, ui_type, selections, *, color=True, stored="auto"):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            manager = SettingsManager(root / "settings.json")
            answers = iter(str(choice) for choice in selections)
            ui = ui_type(color=color, fast=True, input_fn=lambda _prompt: next(answers),
                         output_fn=lambda _text: None)
            menus = []

            def choose(title, options, *, allow_back):
                menus.append((options[1], ui.color))
                return ui.choose(title, options, allow_back=allow_back)

            ui.choose_settings = choose
            game = Game(ui, settings_manager=manager, user_settings=UserSettings(color_mode=stored),
                        saves=SaveManager(root / "saves"))
            game._settings()
            return menus, ui.color, manager.load().color_mode

    def test_first_graphical_color_selection_changes_default_full_to_grayscale(self):
        menus, runtime, stored = self.settings_session(GraphicalColorUI, (2, 11))
        self.assertEqual(menus, [("Color: Full", True), ("Color: Grayscale", False)])
        self.assertFalse(runtime)
        self.assertEqual(stored, "off")

    def test_graphical_color_returns_to_full_without_redundant_auto_step(self):
        menus, runtime, stored = self.settings_session(GraphicalColorUI, (2, 2, 11))
        self.assertEqual(menus, [("Color: Full", True), ("Color: Grayscale", False),
                                 ("Color: Full", True)])
        self.assertTrue(runtime)
        self.assertEqual(stored, "on")

    def test_graphical_label_and_toggle_follow_actual_runtime_color(self):
        menus, runtime, stored = self.settings_session(GraphicalColorUI, (2, 11), color=False)
        self.assertEqual(menus, [("Color: Grayscale", False), ("Color: Full", True)])
        self.assertTrue(runtime)
        self.assertEqual(stored, "on")

    def test_terminal_retains_auto_on_off_cycle_and_automatic_detection(self):
        menus, runtime, stored = self.settings_session(DetectedColorUI, (2, 2, 2, 7))
        self.assertEqual(menus, [("Color mode: Auto", True), ("Color mode: On", True),
                                 ("Color mode: Off", False), ("Color mode: Auto", True)])
        self.assertTrue(runtime)
        self.assertEqual(stored, "auto")


if __name__ == "__main__":
    unittest.main()
