"""Earned objectives and terminal recovery describe the same journey."""

import random
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.checkpoint import CheckpointManager
from roads_beneath_shadow.content import ORIGINS, QUEST_NAMES_LOST, QUEST_THIRD_STONE
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.part_two import QUEST_DEAD_ROAD_LEAD, QUEST_GATE_MARK, begin_part_two
from roads_beneath_shadow.player_view import player_snapshot
from roads_beneath_shadow.savegame import MAX_SAVE_BYTES, SaveManager
from roads_beneath_shadow.settings import SettingsManager
from roads_beneath_shadow.ui import InputClosed, TerminalUI
from tests.helpers import EpisodePlayer, VictoryCombat


class StoryRecoveryPolishTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.saves = SaveManager(self.root / "saves")

    @staticmethod
    def state(scene="bree_exploration"):
        return GameState(Character.from_origin("Éowen", ORIGINS[0]), scene=scene)

    def game(self, answers=(), *, state=None, checkpoint_support=False, screen_reader=False):
        responses = iter(answers)
        output = []
        ui = TerminalUI(
            color=True, fast=True, screen_reader=screen_reader,
            checkpoint_support=checkpoint_support,
            input_fn=lambda _: next(responses), output_fn=output.append,
        )
        game = Game(ui, saves=self.saves, rng=random.Random(31))
        game.state = state
        return game, output

    def test_full_opening_routes_resolve_only_objectives_the_traveler_earned(self):
        for opening, expected in ((1, set()), (3, {QUEST_GATE_MARK}), (5, {QUEST_DEAD_ROAD_LEAD})):
            with self.subTest(opening=opening):
                player = EpisodePlayer(opening_choice=opening)
                game = Game(
                    TerminalUI(color=False, fast=True, input_fn=player.read, output_fn=player.write),
                    saves=self.saves, rng=random.Random(31),
                )
                game.combat = VictoryCombat()
                game.run()
                self.assertIsNotNone(game.state.ending)
                leads = {QUEST_GATE_MARK, QUEST_DEAD_ROAD_LEAD}
                self.assertFalse(leads.intersection(game.state.quests))
                self.assertEqual(leads.intersection(game.state.completed_quests), expected)
                before = list(game.state.completed_quests)
                begin_part_two(game.state)
                self.assertEqual(game.state.completed_quests, before)
                if opening == 5:
                    self.assertIn(
                        "I found the Dead Road beneath the wayhouse. Calenor is still a prisoner; finding the road has not yet brought him home.",
                        game.state.journal,
                    )

    def test_resumed_open_cache_closes_the_earned_gate_lead_without_repeating_rewards(self):
        state = self.state("north_gate")
        state.quests = [QUEST_GATE_MARK]
        state.flags.update({
            "north_gate_intro_seen": True, "north_gate_truth_chosen": True,
            "north_gate_cache_opened": True,
        })
        before_character = state.to_dict()["character"]
        game, _ = self.game(("m",), state=state, checkpoint_support=True)
        self.assertFalse(game._north_gate())
        self.assertNotIn(QUEST_GATE_MARK, state.quests)
        self.assertEqual(state.completed_quests, [QUEST_GATE_MARK])
        self.assertEqual(vars(state.character), before_character)
        self.saves.save(1, state)
        loaded = self.saves.load(1)
        restored, _ = self.game(("m",), state=loaded, checkpoint_support=True)
        self.assertFalse(restored._north_gate())
        self.assertEqual(loaded.to_dict(), state.to_dict())
        self.assertEqual(restored.checkpoints.resume().to_dict(), loaded.to_dict())

    def test_legacy_handoff_resolves_present_leads_without_inventing_missing_ones(self):
        for active in ([], [QUEST_GATE_MARK], [QUEST_DEAD_ROAD_LEAD], [QUEST_GATE_MARK, QUEST_DEAD_ROAD_LEAD]):
            with self.subTest(active=active):
                state = self.state("complete")
                state.ending = "fellowship"
                state.quests = list(active)
                begin_part_two(state)
                self.assertEqual(state.completed_quests, active)
                self.assertFalse(set(active).intersection(state.quests))
                self.saves.save(1, state)
                loaded = self.saves.load(1)
                begin_part_two(loaded)
                self.assertEqual(loaded.to_dict(), state.to_dict())

    def test_bree_exploration_states_the_prerequisite_before_an_early_exit_attempt(self):
        observed = []
        state = self.state()
        game, output = self.game(state=state)

        def choose(heading, options):
            observed.append(tuple(options))
            return None

        game.ui.choose_story = choose
        self.assertFalse(game._bree_exploration())
        self.assertIn("investigate 2 more places first", observed[0][-1])
        self.assertIn("Investigated 0 of 4 places", "\n".join(output))
        self.assertIn("at least two", "\n".join(output))
        self.assertNotIn("north_gate", state.visited)

    def test_bree_prerequisite_progress_counts_only_distinct_completed_investigations(self):
        for visited, count, ready in (
            (["bree_exploration", "messenger_room", "messenger_room"], 1, False),
            (["messenger_room", "stable_yard", "north_gate"], 2, True),
            (["messenger_room", "stable_yard", "pony_kitchen", "mara_fire"], 4, True),
        ):
            with self.subTest(visited=visited):
                state = self.state()
                state.quests = [QUEST_THIRD_STONE]
                state.visited = visited
                before = state.to_dict()
                detail = player_snapshot(state)["quest_details"][0]
                self.assertEqual(detail["progress"], f"{count} of 4 places investigated")
                self.assertEqual("enough places" in detail["guidance"], ready)
                self.assertNotIn("Fornost", str(detail))
                self.assertEqual(state.to_dict(), before)

    def test_terminal_checkpoint_resumes_whole_state_and_keeps_manual_slots_separate(self):
        manual = self.state("north_gate")
        manual.character.name = "Earlier manual journey"
        self.saves.save(2, manual)
        original_manual_bytes = self.saves._path(2).read_bytes()
        state = self.state("midgewater_camp")
        state.flags["midgewater_camp_setup"] = True
        state.character.hp -= 9
        state.journal = ["A recorded clue points toward Midgewater."]
        game, _ = self.game(state=state, checkpoint_support=True, screen_reader=True)
        game._record_checkpoint()
        resumed, output = self.game(("1", "7"), checkpoint_support=True, screen_reader=True)
        with patch.object(resumed, "_run_journey") as journey:
            resumed.run()
        journey.assert_called_once()
        self.assertEqual(resumed.state.to_dict(), state.to_dict())
        self.assertEqual(self.saves._path(2).read_bytes(), original_manual_bytes)
        self.assertIn("Resume checkpoint", "\n".join(output))
        self.assertNotIn("\x1b", "\n".join(output))

    def test_closed_terminal_input_preserves_the_last_safe_story_choice(self):
        state = self.state("north_gate")
        game, output = self.game(state=state, checkpoint_support=True, screen_reader=True)
        game.ui.input_fn = lambda _: (_ for _ in ()).throw(InputClosed())
        with self.assertRaises(InputClosed):
            game._story_choice("A SAFE STORY CHOICE", ["Continue", "Wait"])
        self.assertEqual(game.checkpoints.resume().to_dict(), state.to_dict())
        self.assertNotIn("\x1b", "\n".join(output))

    def test_disabled_terminal_checkpoints_never_write_or_change_manual_saves(self):
        state = self.state()
        self.saves.save(1, state)
        original = self.saves._path(1).read_bytes()
        game, _ = self.game(state=state, checkpoint_support=True)
        game.user_settings.autosave = False
        game._record_checkpoint()
        self.assertFalse(game.checkpoints.path.exists())
        self.assertEqual(self.saves._path(1).read_bytes(), original)

    def test_screen_reader_journal_exposes_known_guidance_progress_and_clues(self):
        state = self.state("part2_hall_exploration")
        state.chapter = 2
        state.quests = [QUEST_NAMES_LOST]
        state.flags["part2_testimony_first"] = True
        state.journal = ["The first Warden testimony answered my road-name."]
        before = state.to_dict()
        game, output = self.game(state=state, screen_reader=True)
        game._show_journal()
        spoken = "\n".join(output)
        self.assertIn("1 of 3 testimonies recovered", spoken)
        self.assertIn("Keep the testimonies you have recovered together", spoken)
        self.assertIn("Known clue: " + state.journal[0], spoken)
        self.assertNotIn("\x1b", spoken)
        self.assertNotIn("Calenor's Prison", spoken)
        self.assertEqual(state.to_dict(), before)

    def test_terminal_combat_guide_explains_free_reads_and_conditional_focus_actions(self):
        state = self.state()
        before = state.to_dict()
        game, output = self.game(state=state, screen_reader=True, checkpoint_support=True)
        game._how_to_play()
        spoken = " ".join("\n".join(output).split())
        self.assertIn("Inspect and changing targets spend no turn", spoken)
        self.assertIn("Attack costs no Focus", spoken)
        self.assertIn("When available, your background's special ability costs 1 Focus", spoken)
        self.assertIn("can be used once per battle", spoken)
        self.assertIn("Scout's offensive ability is unavailable while surviving an invulnerable foe", spoken)
        self.assertIn("When you cannot interrupt an intent, read its warning and consider Defend", spoken)
        self.assertNotIn("\x1b", spoken)
        self.assertEqual(state.to_dict(), before)
        self.assertFalse(game.checkpoints.path.exists())

    def test_terminal_settings_offer_checkpoints_without_graphical_preferences(self):
        manager = SettingsManager(self.root / "settings.json")
        game, output = self.game(("7", "8"), checkpoint_support=True, screen_reader=True)
        game.settings_manager = manager
        game._settings()
        self.assertFalse(manager.load().autosave)
        spoken = "\n".join(output)
        self.assertIn("Automatic checkpoints", spoken)
        self.assertNotIn("Music volume", spoken)
        self.assertNotIn("Reading text size", spoken)
        self.assertIn("Screen-reader mode", spoken)
        self.assertNotIn("\x1b", spoken)

    def test_optional_settings_chooser_preserves_the_existing_menu_contract(self):
        game, _ = self.game()
        selections = iter((3, None))
        menus = []

        def choose_settings(title, options, *, allow_back):
            menus.append((title, tuple(options), allow_back))
            return next(selections)

        game.ui.choose_settings = choose_settings
        game._settings()
        self.assertEqual(game.user_settings.text_speed, "fast")
        self.assertEqual(len(menus), 2)
        self.assertTrue(all(title == "SETTINGS" and back for title, _, back in menus))

    def test_oversized_unicode_save_cannot_replace_a_good_slot_or_checkpoint(self):
        state = self.state()
        self.saves.save(1, state)
        checkpoints = CheckpointManager(self.saves.root)
        checkpoints.record(state)
        originals = {path: path.read_bytes() for path in (self.saves._path(1), checkpoints.path)}
        state.journal = ["é" * 1800] * 600
        for write in (lambda: self.saves.save(1, state), lambda: checkpoints.record(state)):
            with self.subTest(writer=write):
                with self.assertRaisesRegex(ValueError, "too large"):
                    write()
                self.assertFalse(list(self.saves.root.glob("*.tmp")))
                for path, contents in originals.items():
                    self.assertEqual(path.read_bytes(), contents)
        self.assertLess(self.saves._path(1).stat().st_size, MAX_SAVE_BYTES)
        self.assertEqual(self.saves.load(1).journal, [])
        self.assertEqual(checkpoints.resume().journal, [])

    def test_large_unicode_save_within_the_limit_reloads_every_clue(self):
        state = self.state()
        state.journal = ["é" * 1800] * 550
        path = self.saves.save(1, state)
        self.assertLessEqual(path.stat().st_size, MAX_SAVE_BYTES)
        self.assertGreater(path.stat().st_size, MAX_SAVE_BYTES * .95)
        self.assertEqual(self.saves.load(1).to_dict(), state.to_dict())

    def test_oversized_manual_save_reports_failure_and_keeps_previous_memory(self):
        earlier = self.state()
        self.saves.save(1, earlier)
        original = self.saves._path(1).read_bytes()
        state = self.state()
        state.journal = ["é" * 1800] * 600
        game, output = self.game(("1", "1"), state=state, screen_reader=True)
        self.assertFalse(game._save_menu())
        self.assertEqual(self.saves._path(1).read_bytes(), original)
        self.assertIn("Could not save the journey", "\n".join(output))
        self.assertNotIn("Journey saved in slot", "\n".join(output))


if __name__ == "__main__":
    unittest.main()
