"""Names entered through the pointer/controller keyboard remain editor edits."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import subprocess
import sys
import unittest

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from roads_beneath_shadow.pixel_keyboard import KeyboardEdit, NameKeyboard
from roads_beneath_shadow.text_input import TextEntry


class KeyboardImportTests(unittest.TestCase):
    def test_import_does_not_open_sdl_or_require_a_controller(self):
        result = subprocess.run(
            [sys.executable, "-c", "import sys; import roads_beneath_shadow.pixel_keyboard; assert 'pygame' not in sys.modules"],
            cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_closed_keyboard_does_not_edit_a_name(self):
        view = NameKeyboard(None)
        for command in ("up", "down", "left", "right", "confirm", "back"):
            self.assertIsNone(view.command(command))

    def test_uneven_rows_preserve_the_players_column_when_returning_upward(self):
        view = NameKeyboard(None)
        view.open()
        view.command("left")
        self.assertEqual(view.selected_key, "p")
        expected = ("l", "m", "0", "close", "0", "m", "l", "p")
        for command, key in zip(("down",) * 4 + ("up",) * 4, expected):
            view.command(command)
            self.assertEqual(view.selected_key, key)
        view.command("down")
        view.command("right")  # Explicit horizontal movement resets intent.
        self.assertEqual(view.selected_key, "a")
        view.command("up")
        self.assertEqual(view.selected_key, "q")

    def test_case_digits_space_delete_and_back_are_explicit_editor_operations(self):
        view = NameKeyboard(None)
        view.open()
        self.assertEqual(view.command("confirm"), KeyboardEdit("insert", "q"))
        view.command("up")
        self.assertEqual(view.selected_key, "case")
        self.assertIsNone(view.command("confirm"))
        view.command("down")
        self.assertEqual(view.command("confirm"), KeyboardEdit("insert", "Q"))
        view.command("up")
        view.command("up")
        self.assertEqual(view.command("confirm"), KeyboardEdit("insert", "1"))
        view.command("down")
        view.command("right")
        self.assertEqual(view.command("confirm"), KeyboardEdit("insert", " "))
        view.command("right")
        self.assertEqual(view.command("confirm"), KeyboardEdit("backspace"))
        self.assertEqual(view.command("back"), KeyboardEdit("close"))
        self.assertFalse(view.active)
        self.assertIsNone(view.command("confirm"))

    def test_inserts_use_the_existing_editors_selection_unicode_and_limit(self):
        editor = TextEntry(max_length=24)
        editor.insert("Éowen 夜道")
        editor.select_all()
        view = NameKeyboard(None)
        view.open()
        edit = view.command("confirm")
        editor.insert(edit.text)
        self.assertEqual(editor.text, "q")
        editor.insert("é" * 23)
        editor.insert(view.command("confirm").text)
        self.assertEqual(editor.text, "q" + "é" * 23)
        view.command("up")
        view.command("right")
        view.command("right")
        edit = view.command("confirm")
        self.assertEqual(edit.kind, "backspace")
        editor.backspace()
        self.assertEqual(editor.text, "q" + "é" * 22)


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for keyboard rendering")
class KeyboardSDLTests(unittest.TestCase):
    def setUp(self):
        import pygame
        from roads_beneath_shadow.pixel_theme import load_font

        self.pg = pygame
        pygame.display.init()
        pygame.font.init()
        self.screen = pygame.Surface((760, 560), pygame.SRCALPHA)
        self.rect = pygame.Rect(15, 75, 730, 447)
        self.font = load_font(pygame, 23)
        self.small_font = load_font(pygame, 13)
        self.view = NameKeyboard(pygame)
        self.view.open()

    def tearDown(self):
        self.view = self.font = self.small_font = self.screen = None
        self.pg.quit()

    def draw(self, name="Éowen"):
        self.view.draw(self.screen, self.rect, self.font, self.small_font, name)

    def key_rect(self, row, column):
        return next(rect for rect, position in self.view.hit_targets if position == (row, column))

    def click(self, row, column):
        return self.view.handle_event(self.pg.event.Event(
            self.pg.MOUSEBUTTONDOWN, button=1, pos=self.key_rect(row, column).center))

    def test_compact_larger_keyboard_keeps_all_keys_inside_its_modal(self):
        sentinel = (247, 9, 235, 255)
        self.screen.fill(sentinel)
        self.draw("Éowen of the Northern Stars 夜道" * 4)
        self.assertEqual(len(self.view.hit_targets), 41)
        tiles = [rect for rect, _ in self.view.hit_targets]
        self.assertTrue(all(self.rect.contains(tile) for tile in tiles))
        self.assertTrue(all(tile.height >= self.font.get_height() + 8 for tile in tiles))
        for index, tile in enumerate(tiles):
            self.assertTrue(all(not tile.colliderect(other) for other in tiles[index + 1:]))
        # Every pixel outside the caller's modal retains its sentinel value.
        for y in range(self.screen.get_height()):
            for x in range(self.screen.get_width()):
                if not self.rect.collidepoint(x, y):
                    self.assertEqual(self.screen.get_at((x, y)), sentinel)

    def test_draw_preserves_the_callers_clip(self):
        clip = self.rect.inflate(-18, -20)
        self.screen.set_clip(clip)
        self.draw()
        self.assertEqual(self.screen.get_clip(), clip)

    def test_done_cannot_submit_an_empty_or_whitespace_only_name(self):
        self.draw(" ")
        self.assertEqual(self.click(4, 3), (True, None))
        self.assertTrue(self.view.active)
        self.draw("Éowen")
        self.assertEqual(self.click(4, 3), (True, KeyboardEdit("confirm")))
        self.draw("")
        self.assertEqual(self.click(4, 3), (True, None))

    def test_mouse_edit_and_hover_preserve_the_same_navigation_identity(self):
        self.draw()
        self.assertEqual(self.click(4, 0), (True, None))  # Uppercase.
        self.draw()
        self.assertEqual(self.click(1, 8), (True, KeyboardEdit("insert", "L")))
        self.view.command("up")
        self.assertEqual(self.view.selected_key, "o")
        self.assertEqual(self.view.command("confirm"), KeyboardEdit("insert", "O"))
        self.assertEqual(self.click(4, 2), (True, KeyboardEdit("backspace")))
        self.assertEqual(self.click(4, 4), (True, KeyboardEdit("close")))
        self.assertEqual(self.view.hit_targets, [])

    def test_modal_clicks_cannot_activate_the_name_prompt_behind_it(self):
        self.draw()
        event = self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=(1, 1))
        self.assertEqual(self.view.handle_event(event), (True, None))
        right_click = self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=3, pos=self.key_rect(0, 0).center)
        self.assertEqual(self.view.handle_event(right_click), (True, None))
        self.view.close()
        self.assertEqual(self.view.handle_event(event), (False, None))


if __name__ == "__main__":
    unittest.main()
