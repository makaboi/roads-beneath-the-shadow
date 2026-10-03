"""Real SDL coverage for the adventure presentation's engine boundaries."""

from __future__ import annotations

import importlib.util
import os
import random
import threading
import time
import unittest
from unittest.mock import patch

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
os.environ.setdefault("SDL_AUDIODRIVER", "dummy")
os.environ.setdefault("PYGAME_HIDE_SUPPORT_PROMPT", "1")

from roads_beneath_shadow import artwork
from roads_beneath_shadow.app import Game
from roads_beneath_shadow.combat import CombatConfig, CombatEngine, CombatResult
from roads_beneath_shadow.combat_view import CombatCommand
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, Enemy, GameState
from roads_beneath_shadow.pixel_ui import PixelUI, PixelWindow
from roads_beneath_shadow.pixel_world import WORLD_MAPS, WORLD_SIZE
from roads_beneath_shadow.ui import InputClosed


@unittest.skipUnless(importlib.util.find_spec("pygame"), "pygame-ce is needed for presentation integration tests")
class PixelUpgradeSDLTests(unittest.TestCase):
    def setUp(self):
        # Instant text removes timing from these tests; fast=False retains the
        # player's actual paged narrative and exploration presentation.
        self.ui = PixelUI(fast=False, text_speed="instant", sound=False)
        self.window = PixelWindow(self.ui)
        self.pg = self.window.pg
        self.workers = []
        self.results = []
        self.errors = []

    def tearDown(self):
        self.ui.close()
        for worker in self.workers:
            worker.join(timeout=1)
            self.assertFalse(worker.is_alive(), "closing the UI left its story worker blocked")
        self.pg.quit()
        if self.errors:
            self.fail(f"Story worker failed: {self.errors[0]!r}")

    def start(self, method):
        def run():
            try:
                self.results.append(method())
            except InputClosed:
                pass
            except Exception as error:
                self.errors.append(error)

        worker = threading.Thread(target=run, daemon=True)
        self.workers.append(worker)
        worker.start()
        self.await_request()
        return worker

    def await_request(self, predicate=lambda request: True):
        deadline = time.monotonic() + 3
        while time.monotonic() < deadline:
            self.window.drain()
            self.window.render()
            request = self.window.request
            if request is not None and predicate(request):
                return request
            if self.errors:
                self.fail(f"Story worker failed: {self.errors[0]!r}")
            time.sleep(0.002)
        self.fail("The expected graphical input request did not arrive")

    def key(self, key, text=""):
        self.window.handle_event(self.pg.event.Event(self.pg.KEYDOWN, key=key, unicode=text, mod=0))

    def click(self, rect):
        self.window.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=rect.center))

    def resize(self, size):
        # SDL 2 resizes the display surface before posting VIDEORESIZE.
        # Reproduce that contract even with the dummy driver's synthetic event.
        self.pg.display.set_mode(size, self.pg.RESIZABLE)
        self.window.handle_event(self.pg.event.Event(self.pg.VIDEORESIZE, w=size[0], h=size[1]))
        self.window.render()

    def read_pages(self):
        request = self.window.request
        pages = []
        for _ in range(200):
            current = self.window.narrative.current
            if current is not None and (not pages or pages[-1] != current):
                pages.append(current)
            if not self.window.reading:
                return pages
            self.key(self.pg.K_RETURN, "\r")
            self.window.render()
            self.assertIs(self.window.request, request, "reading a page answered the engine request")
        self.fail("Narrative pages did not reach their final choice")

    def test_actual_opening_displays_all_six_illustrations_before_engine_pause_returns(self):
        game = Game(self.ui)
        game.state = GameState(Character.from_origin("Mira", ORIGINS[0]))
        self.ui.state_provider = lambda: game.state
        worker = self.start(game._chapter_one_intro)
        request = self.window.request
        self.assertEqual(request.kind, "pause")
        pages = self.read_pages()
        self.assertGreater(len(pages), 1)
        self.assertTrue(worker.is_alive(), "the story advanced while local pages were being read")
        scenes = []
        for page in pages:
            if not scenes or scenes[-1] != page.scene_caption:
                scenes.append(page.scene_caption)
        self.assertEqual(len(scenes), 6)
        self.assertIn("inn", scenes[0])
        self.assertIn("Mara", scenes[-1])
        displayed = " ".join(line.text for page in pages for line in page.lines)
        for text, _color, _bold in self.window.history:
            if text.strip() and not text.startswith("PART I"):
                self.assertIn(" ".join(text.split()), displayed)
        self.assertEqual(game.state.scene, "chapter1_decision")
        self.key(self.pg.K_RETURN, "\r")
        worker.join(timeout=1)
        self.assertFalse(worker.is_alive())

    def test_story_selection_is_held_until_the_final_page(self):
        self.ui.art(artwork.PRANCING_PONY_INTERIOR_ART, alt_text="A crowded inn waits in silence.")
        self.ui.narrate(" ".join(f"memory{index}" for index in range(180)))
        worker = self.start(lambda: self.ui.choose_story("WHICH ROAD WILL YOU TAKE?", ("The east road", "The west road")))
        request = self.window.request
        self.assertTrue(self.window.reading)
        self.key(self.pg.K_2, "2")
        self.window.render()
        self.assertIs(self.window.request, request)
        self.assertTrue(worker.is_alive())
        self.read_pages()
        self.key(self.pg.K_2, "2")
        worker.join(timeout=1)
        self.assertEqual(self.results, [2])

    def test_first_confirm_finishes_text_reveal_and_the_next_selects_the_choice(self):
        self.ui.set_text_speed("slow")
        self.ui.narrate("Calenor's letter names a third stone beneath the north gate.")
        worker = self.start(lambda: self.ui.choose_story("READ THE LETTER", ("Go to the north gate", "Wait for Mara")))
        request = self.window.request
        self.assertEqual(len(self.window.narrative.pages), 1)
        self.assertTrue(self.window.reading)
        self.key(self.pg.K_RETURN, "\r")
        self.window.render()
        self.assertFalse(self.window.reading)
        self.assertIs(self.window.request, request)
        self.assertTrue(worker.is_alive(), "the reveal confirmation also selected the story choice")
        self.key(self.pg.K_RETURN, "\r")
        worker.join(timeout=1)
        self.assertEqual(self.results, [1])

    def test_map_click_walk_and_e_submit_the_exact_reordered_live_option(self):
        spec = WORLD_MAPS["bree"]
        target = spec.points[1]
        options = (spec.points[4].option, target.option)
        worker = self.start(lambda: self.ui.choose_story("WHERE WILL YOU INVESTIGATE?", options))
        request = self.window.request
        self.assertTrue(self.window.world.active)
        self.assertEqual(self.window.world.map_key, "bree")
        before = self.window.world.player_position
        self.key(self.pg.K_e, "e")
        self.assertIs(self.window.request, request, "interacting at a distance chose a story action")
        rect = self.window.world._rect
        self.assertGreater(rect.width, 0)
        px, py = target.position
        position = (rect.left + round(px * rect.width / WORLD_SIZE[0]), rect.top + round(py * rect.height / WORLD_SIZE[1]))
        self.window.handle_event(self.pg.event.Event(self.pg.MOUSEBUTTONDOWN, button=1, pos=position))
        self.assertEqual(self.window.world.player_position, before, "clicking a place teleported the traveler")
        for _ in range(160):
            self.window.world.update(0.05, reduced_motion=True)
        self.window.render()
        self.assertNotEqual(self.window.world.player_position, before)
        self.assertEqual(self.window.world.focused_option, 2)
        self.assertIs(self.window.request, request)
        self.key(self.pg.K_e, "e")
        worker.join(timeout=1)
        self.assertEqual(self.results, [2])

    def test_world_movement_uses_wasd_without_selecting_a_menu_action(self):
        spec = WORLD_MAPS["bree"]
        self.start(lambda: self.ui.choose_story("WHERE WILL YOU INVESTIGATE?", tuple(point.option for point in spec.points)))
        request = self.window.request
        before = self.window.world.player_position
        self.key(self.pg.K_d, "d")
        self.window.world.update(0.1)
        self.window.handle_event(self.pg.event.Event(self.pg.KEYUP, key=self.pg.K_d))
        self.assertNotEqual(self.window.world.player_position, before)
        self.assertIs(self.window.request, request)
        self.assertEqual(self.results, [])

    def test_releasing_a_walk_key_in_the_transcript_does_not_restart_movement(self):
        spec = WORLD_MAPS["bree"]
        self.start(lambda: self.ui.choose_story("WHERE WILL YOU INVESTIGATE?", tuple(point.option for point in spec.points)))
        request = self.window.request
        self.key(self.pg.K_d, "d")
        self.window.world.update(0.05)
        self.key(self.pg.K_TAB, "\t")
        self.assertTrue(self.window.transcript_open)
        self.window.handle_event(self.pg.event.Event(self.pg.KEYUP, key=self.pg.K_d))
        self.key(self.pg.K_TAB, "\t")
        self.assertFalse(self.window.transcript_open)
        position = self.window.world.player_position
        self.window.world.update(0.1)
        self.assertEqual(self.window.world.player_position, position, "a released key remained held after reading the transcript")
        self.assertIs(self.window.request, request)

    def test_walking_out_of_inspection_transfers_enter_and_pad_confirm_to_local_prompt(self):
        from roads_beneath_shadow.controller_input import PadAction

        spec = WORLD_MAPS["bree"]
        worker = self.start(lambda: self.ui.choose_story(
            "WHERE WILL YOU INVESTIGATE?", tuple(point.option for point in spec.points)
        ))
        request = self.window.request
        for confirm in ("Enter", "gamepad A"):
            with self.subTest(confirm=confirm):
                self.window.world._position = (184.0, 104.0)
                self.key(self.pg.K_DOWN)
                self.assertTrue(self.window._menu_focused)
                self.key(self.pg.K_e, "e")
                self.assertEqual(self.window.world.inspection_title, "Hanging horse sign")
                self.key(self.pg.K_w, "w")
                self.window.world.update(0.05)
                self.window.handle_event(self.pg.event.Event(self.pg.KEYUP, key=self.pg.K_w))
                self.window.render()
                self.assertFalse(self.window.world.inspection_open)
                self.assertFalse(self.window._menu_focused)
                self.assertIn("Look at Hanging horse sign", self.window.world.hint_text)
                if confirm == "Enter":
                    self.key(self.pg.K_RETURN)
                else:
                    self.window._dispatch_pad(PadAction("confirm"))
                self.assertEqual(self.window.world.inspection_title, "Hanging horse sign")
                self.assertIs(self.window.request, request)
                self.assertEqual(self.results, [])
                self.key(self.pg.K_ESCAPE)
        # An explicit menu navigation afterwards still owns confirmation.
        self.key(self.pg.K_DOWN)
        expected = self.window.selected + 1
        self.assertTrue(self.window._menu_focused)
        self.key(self.pg.K_RETURN)
        worker.join(timeout=1)
        self.assertEqual(self.results, [expected])

    def test_character_and_journal_panels_restore_the_exact_story_scene(self):
        game = Game(self.ui)
        game.state = GameState(Character.from_origin("Mira", ORIGINS[0]), scene="chapter1_decision")
        game.state.add_quest("Keep the star safe")
        game.state.add_journal("The third stone bears Calenor's mark.")
        self.ui.state_provider = lambda: game.state
        self.ui.art(artwork.STAR_KEY_BROKEN_ART, alt_text="A broken silver star rests in your hand.")
        worker = self.start(game._chapter_one_decision)
        self.read_pages()
        scene = self.window.scene_key
        position = self.window.world.player_position
        for command, kind in (("j", "journal"), ("c", "character")):
            self.key(ord(command), command)
            panel_request = self.await_request(lambda request: request.kind == "panel")
            self.assertEqual(panel_request.context["kind"], kind)
            self.assertTrue(self.window.panels.active)
            self.assertEqual(self.window.scene_key, scene)
            self.key(self.pg.K_1, "1")
            self.assertIs(self.window.request, panel_request, "an input leaked through the modal to the story")
            self.key(self.pg.K_ESCAPE)
            self.await_request(lambda request: request.story)
            self.assertFalse(self.window.panels.active)
            self.assertEqual(self.window.scene_key, scene)
            self.assertEqual(self.window.world.player_position, position)
            self.assertEqual(game.state.scene, "chapter1_decision")
        self.key(self.pg.K_2, "2")
        worker.join(timeout=1)
        self.assertEqual(self.results, [True])
        self.assertEqual(game.state.scene, "branch_hide")

    def test_clicking_combat_targets_submits_free_commands_without_advancing_the_round(self):
        state = GameState(Character.from_origin("Mira", ORIGINS[0]))
        self.ui.state_provider = lambda: state
        enemies = [
            Enemy("Orc Vanguard", 100, 100, 1, 1, intent_pattern=("heavy",)),
            Enemy("Black-fletched Archer", 100, 100, 1, 1, intent_pattern=("aim",)),
        ]
        engine = CombatEngine(self.ui, random.Random(7))
        worker = self.start(lambda: engine.run(state, enemies, CombatConfig(max_rounds=1)))
        self.assertEqual(self.window.request.kind, "combat")
        self.read_pages()
        self.window.render()
        snapshot = self.window.battle.snapshot
        before = (state.character.hp, state.character.focus, tuple(enemy.hp for enemy in enemies), tuple(enemy.turn_count for enemy in enemies))
        for target_id in ("enemy_1", "enemy_0"):
            request = self.window.request
            rect = next(rect for rect, enemy_id in self.window.battle.enemy_hits if enemy_id == target_id)
            with patch.object(self.ui, "submit", wraps=self.ui.submit) as submit:
                self.click(rect)
                submit.assert_called_once()
                self.assertEqual(submit.call_args.args[1], CombatCommand("target", target_id))
            self.await_request(lambda following: following.kind == "combat" and following.identifier != request.identifier)
            self.assertEqual(self.window.battle.snapshot.target_id, target_id)
            self.assertEqual(self.window.battle.snapshot.round_number, snapshot.round_number)
            self.assertEqual((state.character.hp, state.character.focus, tuple(enemy.hp for enemy in enemies), tuple(enemy.turn_count for enemy in enemies)), before)
        action = next(index for index, option in enumerate(self.window.request.options, 1) if option.startswith("Defend"))
        self.key(self.pg.K_0 + action, str(action))
        worker.join(timeout=1)
        self.assertEqual(self.results, [CombatResult.VICTORY])

    def test_disabled_combat_action_cannot_submit_by_keyboard_or_click(self):
        state = GameState(Character.from_origin("Mira", ORIGINS[0]))
        state.character.max_focus = 1
        self.ui.state_provider = lambda: state
        enemy = Enemy("Armored Vanguard", 100, 100, 1, 1, intent_pattern=("aim",))
        engine = CombatEngine(self.ui, random.Random(7))
        worker = self.start(lambda: engine.run(state, [enemy], CombatConfig(mara_aid=True, max_rounds=2)))
        self.read_pages()
        request = self.window.request
        mara = next(index for index, option in enumerate(request.options, 1) if option.startswith("Mara: Crossing Blades"))
        self.key(self.pg.K_0 + mara, str(mara))
        request = self.await_request(lambda following: following.kind == "combat" and following.identifier != request.identifier)
        self.assertEqual(state.character.focus, 0)
        power = next(index for index, option in enumerate(request.options, 1) if option.startswith("Power attack"))
        before = state.character.hp, enemy.hp, enemy.turn_count
        with patch.object(self.ui, "submit", wraps=self.ui.submit) as submit:
            self.key(self.pg.K_0 + power, str(power))
            rect = next(rect for rect, answer in self.window.choice_hits if answer == power)
            self.click(rect)
            submit.assert_not_called()
        self.assertIs(self.window.request, request)
        self.assertEqual((state.character.hp, enemy.hp, enemy.turn_count), before)
        # Paid moves wait for this round's impacts; an early second key
        # cannot overwrite the action that is still being presented.
        self.window.battle.update(1.5)
        defend = next(index for index, option in enumerate(request.options, 1) if option.startswith("Defend"))
        self.key(self.pg.K_0 + defend, str(defend))
        worker.join(timeout=1)
        self.assertEqual(self.results, [CombatResult.VICTORY])

    def test_completing_a_quest_shows_a_notice_from_the_request_snapshot(self):
        state = GameState(Character.from_origin("Mira", ORIGINS[0]))
        state.add_quest("Read Calenor's letter")
        self.ui.state_provider = lambda: state

        def choose_twice():
            first = self.ui.choose_story("READ THE LETTER", ("Read it",))
            state.complete_quest("Read Calenor's letter")
            second = self.ui.choose_story("THE NORTH ROAD", ("Continue",))
            return first, second

        worker = self.start(choose_twice)
        request = self.window.request
        with patch.object(self.window, "_toast", wraps=self.window._toast) as toast:
            self.key(self.pg.K_1, "1")
            self.await_request(lambda following: following.identifier != request.identifier)
            toast.assert_any_call("Completed: Read Calenor's letter")
        self.key(self.pg.K_1, "1")
        worker.join(timeout=1)
        self.assertEqual(self.results, [(1, 1)])

    def test_responsive_narrative_and_choices_fit_both_supported_window_sizes(self):
        for size in ((760, 560), (1200, 900)):
            with self.subTest(size=size):
                self.resize(size)
                text = " ".join(f"road{index}" for index in range(140))
                self.ui.narrate(text)
                worker = self.start(lambda: self.ui.choose_story("WHERE DOES THE ROAD LEAD?", ("Follow the lantern beyond the ruined gate", "Wait by the fire")))
                pages = self.read_pages()
                self.assertEqual(" ".join(line.text for page in pages for line in page.lines), text)
                screen = self.window.screen.get_rect()
                self.assertEqual(screen.size, size)
                for rect in (self.window.art_rect, self.window.history_rect, self.window.menu_rect):
                    self.assertTrue(screen.contains(rect), f"visible content left the {size} viewport: {rect}")
                for rect, _answer in self.window.choice_hits + self.window.utility_hits:
                    self.assertTrue(screen.contains(rect), "a visible control was outside the window")
                self.assertTrue(all(self.window.font.size(line.text)[0] <= self.window.history_rect.width for page in pages for line in page.lines))
                self.key(self.pg.K_1, "1")
                worker.join(timeout=1)
                self.assertFalse(worker.is_alive())

    def test_resize_reflows_the_current_story_without_skipping_its_reading_position(self):
        self.ui.narrate(" ".join(f"remembered{index}" for index in range(220)))
        self.start(lambda: self.ui.choose_story("A LONG ROAD", ("Continue the journey",)))
        self.key(self.pg.K_RETURN, "\r")
        self.window.render()
        old_anchor = self.window.narrative.current.start
        self.resize((760, 560))
        self.assertLessEqual(self.window.narrative.current.start, old_anchor)
        self.assertTrue(self.window.reading)
        self.assertEqual(self.results, [])

    def test_reduced_motion_keeps_map_art_still_and_walk_controls_work(self):
        self.ui.reduced_motion = True
        spec = WORLD_MAPS["bree"]
        self.start(lambda: self.ui.choose_story("WHERE WILL YOU INVESTIGATE?", tuple(point.option for point in spec.points)))
        with patch.object(self.pg.time, "get_ticks", return_value=1000):
            self.window.render()
        first = self.pg.image.tobytes(self.window.screen.subsurface(self.window.art_rect), "RGB")
        self.window.world.update(0.25, reduced_motion=True)
        with patch.object(self.pg.time, "get_ticks", return_value=9000):
            self.window.render()
        second = self.pg.image.tobytes(self.window.screen.subsurface(self.window.art_rect), "RGB")
        self.assertEqual(first, second, "reduced motion still moved ambient map art")
        before = self.window.world.player_position
        self.key(self.pg.K_d, "d")
        self.window.world.update(0.1, reduced_motion=True)
        self.window.handle_event(self.pg.event.Event(self.pg.KEYUP, key=self.pg.K_d))
        self.assertNotEqual(self.window.world.player_position, before)

    def test_close_during_a_paged_story_releases_the_engine_worker(self):
        self.ui.narrate(" ".join("The shadow follows the winding road." for _ in range(60)))
        worker = self.start(lambda: self.ui.choose_story("THE ROAD AWAITS", ("Keep walking",)))
        self.assertTrue(self.window.reading)
        self.window.handle_event(self.pg.event.Event(self.pg.QUIT))
        worker.join(timeout=1)
        self.assertTrue(self.ui.closed.is_set())
        self.assertFalse(worker.is_alive())


if __name__ == "__main__":
    unittest.main()
