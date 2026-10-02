"""Presentation sequencing must retain prose, artwork, and reading position."""

from __future__ import annotations

import textwrap
import unittest
from types import SimpleNamespace

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.narrative import NarrativeDirector
from roads_beneath_shadow.pixel_ui import InputRequest, PixelUI


def wrap(width: int):
    def measured(text):
        lines = []
        for paragraph in text.split("\n"):
            lines.extend(textwrap.wrap(paragraph, width=width) or [""])
        return lines
    return measured


class NarrativeDirectorTests(unittest.TestCase):
    def director(self):
        director = NarrativeDirector()
        director.record("art", text="first scene", alt_text="The first road.", color="silver")
        director.record("title", text="A ROAD")
        director.record("text", text="One two three four five six seven eight nine ten.", narration=True)
        return director

    def test_pages_fit_and_preserve_every_word_and_color(self):
        director = self.director()
        director.record("text", text="A warning spoken quietly.", color="red", bold=True)
        pages = director.prepare(wrap=wrap(12), rows=2)
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(len(page.lines) <= 2 for page in pages))
        actual = " ".join(line.text for page in pages for line in page.lines)
        self.assertEqual(actual, "One two three four five six seven eight nine ten. A warning spoken quietly.")
        warning = [line for page in pages for line in page.lines if line.color == "red"]
        self.assertTrue(warning)
        self.assertTrue(all(line.bold for line in warning))
        self.assertEqual([page.number for page in pages], list(range(1, len(pages) + 1)))
        self.assertTrue(all(page.total == len(pages) for page in pages))

    def test_a_fitting_paragraph_moves_whole_to_the_following_page(self):
        director = NarrativeDirector()
        director.record("text", text="first\nsecond\nthird", narration=True)
        director.record("text", text="a quiet\nwarning", color="red", bold=True, narration=True)
        pages = director.prepare(wrap=lambda text: text.splitlines(), rows=4)
        self.assertEqual([page.text for page in pages], ["first\nsecond\nthird", "a quiet\nwarning"])
        self.assertEqual(pages[1].start, (0, 1, 0))
        self.assertTrue(all(line.color == "red" and line.bold for line in pages[1].lines))

    def test_long_paragraph_does_not_leave_a_one_line_continuation(self):
        director = NarrativeDirector()
        text = "\n".join(f"line{index}" for index in range(9))
        director.record("text", text=text, narration=True)
        pages = director.prepare(wrap=lambda text: text.splitlines(), rows=8)
        self.assertEqual([len(page.lines) for page in pages], [7, 2])
        self.assertEqual("\n".join(page.text for page in pages), text)
        self.assertEqual(pages[1].start, (0, 0, len(" ".join(f"line{index}" for index in range(7))) + 1))

    def test_single_closing_line_shares_the_last_screen_with_prior_prose(self):
        director = NarrativeDirector()
        text = "\n".join(f"line{index}" for index in range(8))
        director.record("text", text=text, narration=True)
        director.record("text", text="Listen.", color="cyan", narration=True)
        pages = director.prepare(wrap=lambda text: text.splitlines(), rows=8)
        self.assertEqual([len(page.lines) for page in pages], [6, 3])
        self.assertEqual("\n".join(page.text for page in pages), text + "\nListen.")
        self.assertEqual(pages[-1].lines[-1].color, "cyan")

    def test_blank_separators_never_create_empty_screens(self):
        for rows in (1, 2, 3):
            with self.subTest(rows=rows):
                director = NarrativeDirector()
                for text in ("", "One.", "", "", "Two.", "", "Three.", ""):
                    director.record("text", text=text, narration=True)
                pages = director.prepare(wrap=lambda text: [text], rows=rows)
                self.assertTrue(all(page.text.strip() for page in pages))
                self.assertTrue(all(len(page.lines) <= rows for page in pages))
                self.assertEqual(" ".join(" ".join(page.text.split()) for page in pages), "One. Two. Three.")
                self.assertEqual(len(director.beats[0].paragraphs), 8)

    def test_a_heading_separator_does_not_strand_the_heading_on_a_small_screen(self):
        director = NarrativeDirector()
        director.record("text", text="A ROAD", bold=True)
        director.record("text", text="")
        director.record("text", text="first\nsecond\nthird\nfourth", narration=True)
        pages = director.prepare(wrap=lambda text: text.splitlines() or [""], rows=3)
        self.assertEqual([page.text for page in pages], ["A ROAD\nfirst\nsecond", "third\nfourth"])
        self.assertEqual(pages[1].start, (0, 2, len("first second ")))

    def test_small_capacities_preserve_source_without_exceeding_the_screen(self):
        for rows in range(1, 9):
            with self.subTest(rows=rows):
                director = NarrativeDirector()
                texts = [" ".join(f"word{index:02}" for index in range(count)) for count in (1, 6, 20, 2, 9)]
                for text in texts:
                    director.record("text", text=text, narration=True)
                pages = director.prepare(wrap=wrap(18), rows=rows)
                self.assertTrue(all(1 <= len(page.lines) <= rows for page in pages))
                self.assertEqual(" ".join(line.text for page in pages for line in page.lines), " ".join(texts))
                self.assertEqual([page.start for page in pages], sorted(page.start for page in pages))

    def test_art_transitions_retain_text_and_caption_only_illustrations(self):
        director = self.director()
        director.record("art", text="silent interior", alt_text="A crowded inn falls silent.")
        director.record("art", text="messenger", alt_text="A wounded messenger holds a letter.")
        director.record("text", text='"Calenor sent me," he whispers.', color="cyan")
        pages = director.prepare(wrap=wrap(100), rows=10)
        self.assertEqual([page.scene_text for page in pages], ["first scene", "silent interior", "messenger"])
        self.assertEqual(pages[1].text, "A crowded inn falls silent.")
        self.assertEqual(pages[2].lines[0].color, "cyan")

    def test_empty_decorative_art_does_not_create_blank_pages(self):
        director = NarrativeDirector()
        director.record("art", text="decorative frame")
        director.record("art", text="real scene", alt_text="A road at dusk.")
        director.record("text", text="The evening road is still.", narration=True)
        pages = director.prepare(wrap=wrap(100), rows=10)
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0].scene_text, "real scene")
        self.assertFalse(director.has_next)

    def test_short_scene_shares_a_page_with_the_actual_choice(self):
        director = self.director()
        pages = director.prepare(InputRequest(1, "choice", "Which road?", ("Left", "Right"), story=True), wrap=wrap(100), rows=6)
        self.assertEqual(len(pages), 1)
        self.assertFalse(director.has_next)
        self.assertFalse(director.advance())

    def test_combat_and_menu_output_do_not_gate_engine_input(self):
        for label, heading in (("MAIN MENU", "A ROAD"), ("Choose your action", "COMBAT")):
            with self.subTest(label=label):
                director = self.director()
                director.record("title", text=heading)
                director.record("text", text="An enemy raises a blade and prepares to attack.", narration=True)
                pages = director.prepare(SimpleNamespace(label=label), wrap=wrap(8), rows=2)
                self.assertEqual(len(pages), 1)
                self.assertFalse(director.has_next)
                self.assertFalse(director.cinematic)

    def test_explicit_mode_overrides_automatic_detection(self):
        director = self.director()
        self.assertEqual(len(director.prepare(wrap=wrap(8), rows=1, cinematic=False)), 1)
        director.record("text", text="A menu page that was explicitly requested.")
        self.assertGreater(len(director.prepare(wrap=wrap(8), rows=1, cinematic=True)), 1)

    def test_combat_readouts_can_be_replaced_without_losing_the_preceding_story(self):
        director = self.director()
        director.record("title", text="COMBAT")
        director.record("text", text="An Orc raises its cleaver.", narration=True)
        director.record("text", text="-- Round 1 --")
        director.record("text", text="Orc Scout 9/9 < TARGET")
        pages = director.prepare(
            SimpleNamespace(kind="combat", label="Choose your action"),
            wrap=wrap(12), rows=2, cinematic=True, suppress_headers={"combat"},
        )
        self.assertGreater(len(pages), 1)
        self.assertTrue(all(page.heading == "A ROAD" for page in pages))
        self.assertEqual(" ".join(line.text for page in pages for line in page.lines), "One two three four five six seven eight nine ten.")
        self.assertTrue(any(beat.heading == "COMBAT" for beat in director.beats))
        director.repaginate(wrap=wrap(20), rows=3)
        self.assertTrue(all(page.heading == "A ROAD" for page in director.pages))
        director.record("title", text="AFTER THE BLOOD")
        director.record("text", text="Mara lowers her blades.", narration=True)
        following = director.prepare(wrap=wrap(100), rows=9)
        self.assertEqual(following[0].text, "Mara lowers her blades.")

    def test_a_structured_combat_without_intro_does_not_require_an_empty_continue(self):
        director = NarrativeDirector()
        director.record("title", text="COMBAT")
        director.record("text", text="The enemy closes in.", narration=True)
        director.record("text", text="-- Round 1 --")
        self.assertEqual(director.prepare(wrap=wrap(10), rows=1, cinematic=True, suppress_headers={"COMBAT"}), ())
        self.assertIsNone(director.current)
        self.assertFalse(director.has_next)
        self.assertEqual(len(director.beats), 1)

    def test_following_choice_retains_final_pause_page_without_replaying(self):
        director = self.director()
        first = director.prepare(wrap=wrap(12), rows=2)
        while director.has_next:
            self.assertTrue(director.advance())
        final = director.current
        second = director.prepare(wrap=wrap(12), rows=2)
        self.assertEqual(len(second), 1)
        self.assertEqual(second[0].text, final.text)
        self.assertEqual(second[0].scene_text, final.scene_text)
        self.assertEqual(second[0].number, 1)
        self.assertGreater(len(first), 1)

    def test_resize_preserves_the_source_location_without_skipping(self):
        director = NarrativeDirector()
        director.record("text", text=" ".join(f"word{index:02}" for index in range(50)), narration=True)
        director.prepare(wrap=wrap(20), rows=3)
        director.advance()
        director.advance()
        old_anchor = director.current.start
        director.repaginate(wrap=wrap(45), rows=4)
        self.assertLessEqual(director.current.start, old_anchor)
        following = director.pages[director.index + 1:]
        if following:
            self.assertGreater(following[0].start, old_anchor)
        self.assertTrue(all(len(page.lines) <= 4 for page in director.pages))

    def test_clear_keeps_prior_beats_and_resets_heading_for_new_scene(self):
        director = self.director()
        director.record("clear")
        director.record("art", text="second road", alt_text="A second road.")
        director.record("text", text="A traveler waits.", narration=True)
        pages = director.prepare(wrap=wrap(100), rows=10)
        self.assertEqual([page.scene_text for page in pages], ["first scene", "second road"])
        self.assertEqual(pages[0].heading, "A ROAD")
        self.assertEqual(pages[1].heading, "THE ROAD AWAITS")

    def test_separately_rendered_utility_output_can_be_discarded(self):
        director = self.director()
        director.prepare(wrap=wrap(100), rows=10)
        story_page = director.current
        director.record("title", text="JOURNAL")
        director.record("text", text="A utility entry.")
        director.discard_pending()
        director.prepare(wrap=wrap(100), rows=10)
        self.assertEqual(director.current.text, story_page.text)
        director.record("text", text="The road continues.", narration=True)
        director.prepare(wrap=wrap(100), rows=10)
        self.assertEqual(director.current.heading, story_page.heading)
        self.assertEqual(director.current.scene_text, story_page.scene_text)

    def test_real_chapter_intro_retains_every_paragraph_and_all_six_scenes(self):
        # Exercise the actual engine output; only its blocking final pause is
        # replaced.  The pure presentation model never imports Pygame.
        ui = PixelUI(fast=True)
        ui.pause = lambda message="": None
        game = Game(ui)
        game.state = GameState(Character.from_origin("Mira", ORIGINS[0]))
        game._chapter_one_intro()
        director = NarrativeDirector()
        texts = []
        illustrations = []
        while not ui.events.empty():
            event = ui.events.get_nowait()
            director.feed(event)
            if event.kind == "text":
                texts.append(event.data["text"])
            elif event.kind == "art":
                illustrations.append((event.data["text"], event.data["alt_text"]))
        pages = director.prepare(InputRequest(1, "pause", "Continue"), wrap=wrap(62), rows=9)
        self.assertGreater(len(pages), 1)
        self.assertEqual(len(illustrations), 6)
        seen = []
        for page in pages:
            scene = (page.scene_text, page.scene_caption)
            if not seen or seen[-1] != scene:
                seen.append(scene)
        self.assertEqual(seen, illustrations)
        displayed = " ".join(line.text for page in pages for line in page.lines)
        for text in texts:
            self.assertIn(" ".join(text.split()), displayed)
        self.assertTrue(all(len(page.lines) <= 9 for page in pages))
        self.assertEqual(game.state.scene, "chapter1_decision")


if __name__ == "__main__":
    unittest.main()
