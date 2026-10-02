"""Search and reading the archive must leave the pending game request alone."""

from __future__ import annotations

import importlib.util
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.pixel_transcript import TranscriptView
from roads_beneath_shadow.pixel_ui import PixelUI, PixelWindow
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.ui import InputClosed


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for archive controls")
class TranscriptTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import pygame
        cls.pg = pygame
        pygame.init()

    @classmethod
    def tearDownClass(cls):
        cls.pg.quit()

    def setUp(self):
        self.view = TranscriptView(self.pg)
        self.screen = self.pg.Surface((760, 560))
        self.rect = self.pg.Rect(23, 75, 714, 447)

    def draw(self, size=None):
        if size:
            self.screen = self.pg.Surface(size)
            self.rect = self.pg.Rect(23, 75, size[0] - 46, size[1] - 113)
        self.view.draw(self.screen, self.rect)

    def key(self, key, *, mod=0):
        return self.view.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=key, mod=mod, unicode=""))

    def search(self, query):
        self.key(self.pg.K_f, mod=self.pg.KMOD_CTRL)
        self.view.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text=query))
        self.draw()

    def visible_lines(self):
        end = len(self.view._lines) - self.view.scroll
        return self.view._lines[max(0, end - self.view.rows):end]

    def test_phrase_in_a_long_entry_is_found_at_its_position_across_wraps(self):
        source = "The road continues. " * 140 + "Mara recognized the silver star before she admitted knowing Calenor." + " The rain falls." * 50
        self.view.open([(source, None, False)])
        self.draw()
        self.search("silver star")
        self.assertIn("silver star", " ".join(line[0] for line in self.visible_lines()))
        self.assertEqual(self.view.matches, [0])
        self.assertGreater(self.view.reading_anchor[1], 1000)
        self.assertEqual(self.view.entries[0][0], source)
        self.draw((1920, 1080))
        self.assertIn("silver star", " ".join(line[0] for line in self.visible_lines()))
        self.assertEqual(self.view.entries[0][0], source)

    def test_unicode_folding_canonical_accents_and_whitespace_preserve_source(self):
        source = "Straße, STRASSE, and a silver\nstar. E\u0301owen remembers the road."
        self.view.open([(source, None, False)])
        self.draw()
        self.search("strasse")
        self.assertEqual(self.view.matches, [0, 0])
        self.assertEqual(self.view._match_positions, [(0, 0, 6), (0, 8, 15)])
        self.key(self.pg.K_RETURN)
        self.assertEqual(self.view.match_index, 1)
        self.search("silver star")
        self.assertEqual(self.view.matches, [0])
        self.search("éowen")
        self.assertEqual(self.view.matches, [0])
        self.assertEqual(self.view.entries[0][0], source)

    def test_reopening_retains_query_and_place_but_requires_search_focus_to_edit(self):
        entries = [(f"Remembered road {index}.", None, False) for index in range(100)]
        self.view.open(entries)
        self.draw()
        self.search("road 20")
        place = self.view.reading_anchor
        self.view.close()
        self.view.open(entries)
        self.draw()
        self.assertFalse(self.view.searching)
        self.assertEqual(self.view.reading_anchor, place)
        self.assertIn("F3: next", self.view.footer_lines()[1])
        self.assertNotIn("end search", self.view.footer_lines()[1])
        self.view.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="ignored"))
        self.assertEqual(self.view.query, "road 20")
        self.search("road 30")
        self.assertEqual(self.view.query, "road 30")
        self.assertFalse(self.key(self.pg.K_ESCAPE))
        self.assertFalse(self.view.searching)
        self.assertTrue(self.key(self.pg.K_ESCAPE))

    def test_focused_search_caret_and_selection_edit_the_query_without_scrolling(self):
        self.view.open([(f"Memory {index}: the silver star and the silver moon.", None, False) for index in range(40)])
        self.draw()
        self.search("silver star")
        place = self.view.reading_anchor
        self.key(self.pg.K_HOME)
        self.assertEqual(self.view.reading_anchor, place)
        self.view.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="the "))
        self.assertEqual(self.view.query, "the silver star")
        self.assertEqual(len(self.view.matches), 40)
        self.key(self.pg.K_LEFT, mod=self.pg.KMOD_CTRL | self.pg.KMOD_SHIFT)
        self.view.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="a "))
        self.assertEqual(self.view.query, "a silver star")
        self.key(self.pg.K_END)
        self.key(self.pg.K_LEFT, mod=self.pg.KMOD_CTRL)
        self.key(self.pg.K_DELETE)
        self.assertEqual(self.view.query, "a silver tar")
        self.view.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="s"))
        self.assertEqual(self.view.query, "a silver star")
        self.key(self.pg.K_LEFT)
        self.key(self.pg.K_END, mod=self.pg.KMOD_SHIFT)
        self.view.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="moon"))
        self.assertEqual(self.view.query, "a silver moon")
        self.key(self.pg.K_ESCAPE)
        self.draw()
        self.key(self.pg.K_HOME)
        self.assertEqual(self.view.scroll, self.view.maximum_scroll)

    def test_query_pointer_caret_and_selected_paste_preserve_word_boundaries(self):
        self.view.open([("the silver bright star remembers", None, False)])
        self.draw()
        self.search("silver star")
        position = (self.view._query_text_x + self.view.small_font.size("silver ")[0], self.view._search_field.centery)
        self.view.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=position))
        self.view.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONUP, button=1, pos=position))
        self.view.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="bright "))
        self.assertEqual(self.view.query, "silver bright star")
        self.assertEqual(self.view.matches, [0])
        self.key(self.pg.K_a, mod=self.pg.KMOD_CTRL)
        self.view.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="silver\nbright\tstar"))
        self.assertEqual(self.view.query, "silver bright star")
        self.assertEqual(self.view.matches, [0])

    def test_enlarged_search_footer_and_close_button_fit_the_minimum_view(self):
        self.view.open([(f"A remembered trail {index} leads through the rain.", None, False) for index in range(500)])
        self.draw()
        self.search("remembered trail")
        self.view.match_index = 499
        self.view._show_match()
        drawn = []
        original_text = self.view._text

        def record_text(surface, text, position, *args, **kwargs):
            font = kwargs.get("font", self.view.font)
            drawn.append((text, position, font.get_linesize()))
            return original_text(surface, text, position, *args, **kwargs)

        self.view._text = record_text
        self.view.draw(self.screen, self.rect, text_size="larger")
        close = next(hit for hit, action in self.view._hits if action == "close")
        self.assertTrue(self.rect.contains(close))
        footer = [(text, position, height) for text, position, height in drawn if position[1] > self.view._content.bottom]
        self.assertTrue(footer)
        self.assertTrue(all(position[1] + height <= self.rect.bottom for _, position, height in footer))
        self.assertIn("remembered trail", " ".join(line[0] for line in self.visible_lines()))
        self.assertTrue(self.view.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=close.center)))

    def test_resize_and_new_entries_keep_the_source_line_being_read(self):
        entries = [(f"Memory {index}: " + "Old roads remember every footstep. " * 8, None, False) for index in range(60)]
        self.view.open(entries)
        self.draw()
        self.key(self.pg.K_HOME)
        self.key(self.pg.K_PAGEDOWN)
        old = self.view.reading_anchor
        self.draw((1440, 900))
        current = self.view.reading_anchor
        self.assertLessEqual(current, old)
        top = len(self.view._lines) - self.view.scroll - self.view.rows
        following = self.view._lines[top + 1][3], self.view._line_spans[top + 1][0]
        self.assertGreater(following, old)
        self.view.set_entries(entries + [("A new scene has arrived.", None, False)])
        self.draw()
        self.assertEqual(self.view.reading_anchor, current)
        self.draw((1440, 1050))
        self.assertEqual(self.view.reading_anchor, current)

    def test_replaced_entries_and_blank_paragraphs_are_not_lost_by_length_cache(self):
        supplied = [("An old note.\n\nA second paragraph.", None, False)]
        self.view.open(supplied)
        self.draw()
        self.assertEqual([line[0] for line in self.view._lines], ["An old note.", "", "A second paragraph."])
        self.search("old note")
        replacement = [("A new note.\n\nThe original is replaced.", None, True)]
        self.view.set_entries(replacement)
        replacement[0] = ("Changed by the caller.", None, False)
        self.draw()
        self.assertEqual(self.view.matches, [])
        self.assertEqual(self.view.entries[0][0], "A new note.\n\nThe original is replaced.")
        self.assertIn("The original is replaced.", [line[0] for line in self.view._lines])

    def test_composed_text_does_not_erase_or_commit_the_query_before_text_input(self):
        source = "Mara waits at the café. Café lanterns shine."
        self.view.open([(source, None, False)])
        self.draw()
        self.search("mara")
        self.key(self.pg.K_f, mod=self.pg.KMOD_CTRL)
        self.view.handle_event(self.pg.event.Event(self.pg.TEXTEDITING, text="café", start=0, length=4))
        self.key(self.pg.K_RETURN)
        self.key(self.pg.K_BACKSPACE)
        self.assertEqual(self.view.query, "mara")
        self.view.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="café"))
        self.draw()
        self.assertEqual(self.view.query, "café")
        self.assertEqual(self.view.matches, [0, 0])
        self.assertEqual(self.view.match_index, 0)
        self.assertEqual(self.view.entries[0][0], source)

    def test_mouse_scrollbar_drag_and_pointer_buttons_reach_archive_and_matches(self):
        self.view.open([(f"Recorded sign {index}", None, False) for index in range(100)])
        self.draw()
        track, thumb = self.view._scrollbar, self.view._thumb
        self.view.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=thumb.center))
        self.view.handle_event(self.pg.event.Event(self.pg.MOUSEMOTION, pos=(track.centerx, track.top - 50), rel=(0, -50), buttons=(1, 0, 0)))
        self.assertEqual(self.view.scroll, self.view.maximum_scroll)
        self.view.handle_event(self.pg.event.Event(self.pg.WINDOWFOCUSLOST))
        self.assertIsNone(self.view._dragging)
        self.search("sign 2")
        hit = next(hit for hit, action in self.view._hits if action == "next")
        self.view.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=hit.center))
        self.assertEqual(self.view.match_index, 1)
        self.key(self.pg.K_ESCAPE)
        self.key(self.pg.K_F3, mod=self.pg.KMOD_SHIFT)
        self.assertEqual(self.view.match_index, 0)
        hit = next(hit for hit, action in self.view._hits if action == "close")
        self.assertTrue(self.view.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=hit.center)))


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for integrated archive input")
class TranscriptWindowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.ui = PixelUI(fast=False, text_speed="instant", sound=False)
        self.window = PixelWindow(self.ui, size=(760, 560))
        self.pg = self.window.pg
        self.game = Game(self.ui, saves=SaveManager(Path(self.temp.name) / "saves"))
        self.game.state = GameState(Character.from_origin("Éowen", ORIGINS[1]), scene="bree_exploration")
        self.ui.state_provider = lambda: self.game.state
        self.worker = None
        self.results = []
        self.errors = []

    def tearDown(self):
        self.ui.close()
        if self.worker:
            self.worker.join(1)
            self.assertFalse(self.worker.is_alive())
        self.pg.quit()
        self.temp.cleanup()
        self.assertEqual(self.errors, [])

    def start(self, method):
        def run():
            try:
                self.results.append(method())
            except InputClosed:
                pass
            except Exception as error:
                self.errors.append(error)
        self.worker = threading.Thread(target=run)
        self.worker.start()
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            self.window.drain()
            self.window.render()
            if self.window.request:
                return
            time.sleep(0.002)
        self.fail("The pending game request did not arrive")

    def key(self, key, *, mod=0, text=""):
        self.window.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=key, unicode=text, mod=mod))

    def test_search_close_reopen_and_resize_preserve_the_live_story_and_world(self):
        source = "The rain falls. " * 50 + "Éowen crossed the Straße and found the silver star." + " An old road waits. " * 80
        self.ui.narrate(source)
        self.start(lambda: self.game._story_choice("WHERE WILL YOU INVESTIGATE?", ("Visit the stable yard", "Go to the north gate")))
        while self.window.reading:
            self.key(self.pg.K_RETURN)
            self.window.render()
        request = self.window.request
        state = self.game.state.to_dict()
        position = self.window.world.player_position
        page = self.window.narrative.current.start
        history = tuple(self.window.history)
        self.key(self.pg.K_TAB)
        self.window.render()
        self.key(self.pg.K_f, mod=self.pg.KMOD_CTRL)
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="strasse"))
        self.window.render()
        self.assertTrue(self.window.archive.matches)
        for key in (self.pg.K_2, self.pg.K_e, self.pg.K_F5, self.pg.K_F1, self.pg.K_RETURN):
            self.key(key)
        self.assertIs(self.window.request, request)
        self.assertEqual(self.results, [])
        self.assertEqual(self.game.state.to_dict(), state)
        self.key(self.pg.K_ESCAPE)
        self.assertTrue(self.window.transcript_open)
        self.assertFalse(self.window.archive.searching)
        self.key(self.pg.K_TAB)
        self.key(self.pg.K_TAB)
        self.window.render()
        self.assertFalse(self.window.archive.searching)
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="should not edit"))
        self.assertEqual(self.window.archive.query, "strasse")
        self.window.handle_event(self.pg.event.Event(self.pg.VIDEORESIZE, w=1440, h=900))
        self.window.render()
        self.key(self.pg.K_ESCAPE)
        self.assertFalse(self.window.transcript_open)
        self.assertEqual(self.window.world.player_position, position)
        self.assertLessEqual(self.window.narrative.current.start, page)
        self.assertEqual(tuple(self.window.history), history)
        self.assertIn(source.strip(), [entry[0] for entry in self.window.archive.entries])
        self.assertEqual(self.game.state.to_dict(), state)
        while self.window.reading:
            self.key(self.pg.K_RETURN)
            self.window.render()
        self.key(self.pg.K_2, text="2")
        self.worker.join(1)
        self.assertEqual(self.results, [2])

    def test_archive_and_local_help_do_not_write_into_the_pending_name_field(self):
        self.ui.write("Éowen remembers a lantern.")
        self.start(lambda: self.ui.prompt("Traveler's name:"))
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="Mira"))
        request = self.window.request
        self.key(self.pg.K_TAB)
        self.window.render()
        self.key(self.pg.K_f, mod=self.pg.KMOD_GUI)
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="éowen"))
        self.key(self.pg.K_TAB)
        self.assertEqual(self.window.entry, "Mira")
        self.assertIs(self.window.request, request)
        self.key(self.pg.K_F1)
        self.assertTrue(self.window.panels.active)
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="ignored"))
        self.key(self.pg.K_RETURN)
        self.assertFalse(self.window.panels.active)
        self.assertEqual(self.window.entry, "Mira")
        self.assertIs(self.window.request, request)
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="é"))
        self.key(self.pg.K_RETURN)
        self.worker.join(1)
        self.assertEqual(self.results, ["Miraé"])

    def test_composition_navigation_keeps_the_query_insertion_point_and_live_request(self):
        source = "The silver bright star remembers the road."
        self.ui.write(source)
        self.start(lambda: self.game._story_choice("A QUIET STOP", ("Stay", "Continue")))
        request = self.window.request
        state = self.game.state.to_dict()
        history = tuple(self.window.history)
        self.key(self.pg.K_TAB)
        self.window.render()
        self.key(self.pg.K_f, mod=self.pg.KMOD_CTRL)
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="silver star"))
        self.key(self.pg.K_HOME)
        self.key(self.pg.K_RIGHT, mod=self.pg.KMOD_CTRL)
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTEDITING, text="bright ", start=0, length=7))
        for key, mod in ((self.pg.K_HOME, 0), (self.pg.K_LEFT, 0), (self.pg.K_END, 0), (self.pg.K_a, self.pg.KMOD_CTRL)):
            self.key(key, mod=mod)
        self.window.handle_event(self.pg.event.Event(self.pg.TEXTINPUT, text="bright "))
        self.window.render()
        self.assertEqual(self.window.archive.query, "silver bright star")
        self.assertTrue(self.window.archive.matches)
        self.assertIn(source, [entry[0] for entry in self.window.archive.entries])
        self.assertIs(self.window.request, request)
        self.assertEqual(tuple(self.window.history), history)
        self.assertEqual(self.game.state.to_dict(), state)
        self.assertEqual(self.results, [])


if __name__ == "__main__":
    unittest.main()
