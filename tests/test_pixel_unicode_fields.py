"""Exercise shaped text in the actual desktop editors without rewriting it."""

from __future__ import annotations

import importlib.util
import os
import threading
import time
import unittest
from unittest.mock import patch
from unicodedata import category

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from roads_beneath_shadow.pixel_theme import load_font
from roads_beneath_shadow.pixel_battle import BattleView
from roads_beneath_shadow.pixel_transcript import TranscriptView
from roads_beneath_shadow.pixel_ui import AMBER, PixelUI, PixelWindow, wrap_pixels
from roads_beneath_shadow.ui import InputClosed


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for Unicode desktop fields")
class UnicodeFieldTests(unittest.TestCase):
    def setUp(self):
        self.ui = PixelUI(fast=True, sound=False)
        self.window = PixelWindow(self.ui, size=(760, 560))
        self.pg = self.window.pg
        self.workers = []
        self.answers = []

    def tearDown(self):
        self.ui.close()
        for worker in self.workers:
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive(), "Unicode field left its input worker blocked")
        self.pg.quit()

    def start_name(self):
        def prompt():
            try:
                self.answers.append(self.ui.choose_name("Traveler's name: "))
            except InputClosed:
                pass

        worker = threading.Thread(target=prompt)
        self.workers.append(worker)
        worker.start()
        deadline = time.monotonic() + 2
        while self.window.request is None and time.monotonic() < deadline:
            self.window.drain()
            time.sleep(0.002)
        self.assertIsNotNone(self.window.request)
        self.window.render()

    def record_geometry(self, draw):
        lines, rectangles = [], []
        native_line, native_rect = self.pg.draw.line, self.pg.draw.rect

        def line(surface, color, start, end, *args, **kwargs):
            lines.append((color, start, end))
            return native_line(surface, color, start, end, *args, **kwargs)

        def rect(surface, color, rectangle, *args, **kwargs):
            rectangles.append((color, self.pg.Rect(rectangle)))
            return native_rect(surface, color, rectangle, *args, **kwargs)

        with patch.object(self.pg.draw, "line", side_effect=line), patch.object(
            self.pg.draw, "rect", side_effect=rect
        ), patch.object(self.pg.time, "get_ticks", return_value=0):
            draw()
        return lines, rectangles

    def name_caret(self, field):
        lines, rectangles = self.record_geometry(lambda: self.window._render_name_entry(field))
        caret = next(start[0] for color, start, end in lines
                     if color == AMBER and start[0] == end[0] and start[1] == field.top + 19)
        return caret, rectangles

    def test_name_caret_does_not_reverse_inside_a_hindi_conjunct(self):
        self.start_name()
        self.window.font = load_font(self.pg, 22)
        self.window.entry = "श्रद्धा"
        field = self.pg.Rect(20, 30, 400, 65)
        self.window._entry_editor.move_to(2)
        before, _ = self.name_caret(field)
        self.window._entry_editor.move_to(3, select=True)
        after, rectangles = self.name_caret(field)
        self.assertGreaterEqual(after, before)
        highlights = [rect for color, rect in rectangles if color == (42, 63, 66)]
        self.assertEqual(len(highlights), 1)
        self.assertGreaterEqual(highlights[0].width, 2)
        self.assertEqual(self.window._entry_editor.selection, (2, 3))
        self.assertEqual(self.window.entry, "श्रद्धा")

    def test_name_pointer_positions_follow_the_visible_shaped_text(self):
        self.start_name()
        self.window.entry = "श्रद्धा 夜道 Éowen"
        field = self.pg.Rect(20, 30, 170, 65)
        self.window._entry_editor.home()
        self.name_caret(field)
        positions = []
        for pointer_x in range(field.left + 11, field.right - 11, 2):
            self.window.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1,
                                                        pos=(pointer_x, field.centery)))
            positions.append(self.window._entry_editor.cursor)
        self.assertEqual(positions, sorted(positions))
        self.assertTrue(all(position <= self.window._entry_view_end for position in positions))
        self.assertEqual(self.window.entry, "श्रद्धा 夜道 Éowen")

    def test_mixed_name_and_cjk_selector_reach_the_pending_request_unchanged(self):
        self.start_name()
        name = "㐂\U000e0100 श्रद्धा Éowen 한길"
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text=name))
        self.window.render()
        self.window.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_RETURN, mod=0, unicode=""))
        self.workers[-1].join(timeout=1)
        self.assertEqual(self.answers, [name])

    def test_name_limit_counts_the_original_source_characters(self):
        self.start_name()
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="夜" * 25))
        self.window.render()
        self.window.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_RETURN, mod=0, unicode=""))
        self.workers[-1].join(timeout=1)
        self.assertEqual(self.answers, ["夜" * 24])

    def test_scrolled_names_do_not_begin_with_a_detached_selector_or_accent(self):
        self.start_name()
        for name in ("㐂\U000e0100" * 12, "か\u3099" * 12):
            with self.subTest(name=name):
                self.window.entry = name
                self.window._entry_editor.end()
                self.window._entry_view_start = 0
                self.ui.text_size = "larger"
                self.window.render()
                begin, end = self.window._entry_view_start, self.window._entry_view_end
                self.assertGreater(begin, 0, "The compact field must exercise horizontal scrolling")
                self.assertEqual(begin % 2, 0)
                self.assertEqual(end % 2, 0)
                self.assertFalse(category(name[begin]).startswith("M"))
                self.assertEqual(self.window.entry, name)

    def test_archive_selection_and_caret_share_shaped_geometry_after_resize(self):
        view = TranscriptView(self.pg)
        source = "श्रद्धा 夜道 Éowen 한길 remembers the road."
        view.open([(source, None, False)])
        view.query = "श्रद्धा"
        view._find_matches()
        view._start_search(select=False)
        rect = self.pg.Rect(23, 40, 714, 480)
        view._query_editor.move_to(2)

        def draw():
            return self.record_geometry(lambda: view.draw(self.window.screen, rect, text_size="larger"))

        def query_caret(lines):
            return next(start[0] for color, start, end in lines if color == AMBER
                        and start[0] == end[0] and start[1] == view._search_field.y + 7)

        before = query_caret(draw()[0])
        view._query_editor.move_to(3, select=True)
        lines, rectangles = draw()
        self.assertGreaterEqual(query_caret(lines), before)
        highlights = [rectangle for color, rectangle in rectangles if color == (49, 69, 68)]
        self.assertEqual(len(highlights), 1)
        self.assertGreaterEqual(highlights[0].width, 2)
        self.assertEqual(view._query_editor.selection, (2, 3))
        self.assertEqual(view._match_positions, [(0, 0, len(view.query))])
        rect.width = 480
        draw()
        self.assertEqual(view.query, "श्रद्धा")
        self.assertEqual(view.entries[0][0], source)

    def test_archive_ime_waits_for_committed_text_then_finds_the_original_source(self):
        view = TranscriptView(self.pg)
        source = "夜道 㐂\U000e0100 श्रद्धा"
        view.open([(source, None, False)])
        view.draw(self.window.screen, self.pg.Rect(23, 40, 714, 480))
        view._start_search()
        view.handle_event(self.pg.event.Event(self.pg.TEXTEDITING, text="㐂\U000e0100", start=0, length=2))
        view.draw(self.window.screen, self.pg.Rect(23, 40, 714, 480))
        view.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=self.pg.K_RETURN, mod=0, unicode=""))
        self.assertEqual(view.query, "")
        view.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="㐂\U000e0100"))
        view.draw(self.window.screen, self.pg.Rect(23, 40, 714, 480))
        self.assertEqual(view._match_positions, [(0, 3, 5)])
        self.assertEqual(view.entries[0][0], source)

    def test_scrolled_archive_queries_do_not_cut_conjuncts_or_variation_sequences(self):
        view = TranscriptView(self.pg)
        rect = self.pg.Rect(22, 40, 716, 480)
        for query, cluster_endings in (("旅" * 12 + "श्रद्धा" * 6, {"旅", "श्र", "द्धा"}),
                                      ("旅" * 12 + "नमस्ते" * 6, {"旅", "न", "म", "स्ते"}),
                                      ("㐂\U000e0100" * 30, {"㐂\U000e0100"})):
            with self.subTest(query=query):
                view.open([(query, None, False)])
                view.query = query
                view._find_matches()
                view._start_search(select=False)
                for caret in (0, len(query)):
                    view._query_editor.move_to(caret)
                    view.draw(self.window.screen, rect, text_size="larger")
                    begin, end = view._query_view_start, view._query_view_end
                    visible = query[begin:end]
                    self.assertTrue(visible)
                    self.assertFalse(category(visible[0]).startswith("M"))
                    self.assertTrue(any(visible.endswith(ending) for ending in cluster_endings))
                    self.assertFalse(visible.endswith("्"))
                    if "\U000e0100" in query:
                        self.assertEqual((begin % 2, end % 2), (0, 0))
                    self.assertEqual(view.query, query)
                    self.assertEqual(view.entries[0][0], query)

    def test_story_wrapping_keeps_conjuncts_and_variation_sequences_intact(self):
        font = load_font(self.pg, 22)
        for source, chunks in (("श्रद्धाश्रद्धा", ["श्र", "द्धा"]),
                               ("㐂\U000e0100㐂\U000e0100", ["㐂\U000e0100"])):
            with self.subTest(source=source):
                lines = wrap_pixels(source, font, 1)
                self.assertEqual("".join(lines), source)
                self.assertTrue(all(line in chunks for line in lines))

    def test_compact_battle_names_elide_at_whole_conjunct_boundaries(self):
        name = "श्रद्धा" * 3
        valid_ends = {0, 3, 7, 10, 14, 17, 21}
        for size in (13, 17, 23):
            font = load_font(self.pg, size)
            for width in range(30, 201):
                label = BattleView._elided_name(name, font, width)
                self.assertLessEqual(font.size(label)[0], width)
                if label.endswith("…"):
                    self.assertIn(len(label) - 1, valid_ends, (size, width, label))
                else:
                    self.assertEqual(label, name)

    def test_small_window_hud_keeps_complete_name_clusters_and_episode_suffix(self):
        name = "旅" * 14 + "द्धा" * 2
        self.window.hud = {"name": name, "hp": 28, "max_hp": 28, "focus": 3,
                           "max_focus": 3, "hope": 0, "corruption": 0, "chapter": 1}
        labels = []
        native_text = self.window._text

        def record(text, *args, **kwargs):
            if "  |  Part " in text:
                labels.append(text)
            return native_text(text, *args, **kwargs)

        with patch.object(self.window, "_text", side_effect=record):
            self.ui.text_size = "larger"
            self.window.render()
        self.assertEqual(len(labels), 1)
        displayed_name, episode = labels[0].split("  |  ")
        self.assertEqual(episode, "Part 1")
        self.assertTrue(displayed_name.endswith("…"), "Compact HUD must exercise name elision")
        self.assertIn(len(displayed_name) - 1, set(range(15)) | {18})
        self.assertEqual(self.window.hud["name"], name)


if __name__ == "__main__":
    unittest.main()
