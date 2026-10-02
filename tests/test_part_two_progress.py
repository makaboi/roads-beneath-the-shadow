"""Exploration and learned truths survive leaving a scene partway through."""

import tempfile
import unittest
from pathlib import Path

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.content import ORIGINS, QUEST_NAMES_LOST
from roads_beneath_shadow.models import VALID_SCENE_IDS, Character, GameState
from roads_beneath_shadow.part_two import PartTwoEpisode, part_two_ending_breakdown
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.ui import TerminalUI


class PartTwoProgressTests(unittest.TestCase):
    @staticmethod
    def state(scene):
        return GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            journey_id="interrupted-road",
            chapter=2,
            scene=scene,
            flags={"part2_spoke_road_name": True},
        )

    def episode(self, answers, menus=None):
        choices = iter(answers)

        def choose(heading, options):
            if menus is not None:
                menus.append((heading, tuple(options)))
            answer = next(choices)
            if answer is None:
                return None
            return next(index + 1 for index, option in enumerate(options) if answer in option)

        return PartTwoEpisode(
            TerminalUI(color=False, fast=True, output_fn=lambda _: None),
            choose,
            lambda *_: self.fail("Learning clues must not start combat"),
        )

    @staticmethod
    def saved_copy(state):
        with tempfile.TemporaryDirectory() as directory:
            saves = SaveManager(Path(directory))
            saves.save(1, state)
            return saves.load(1)

    def test_hall_save_after_each_room_preserves_discoveries_and_remaining_options(self):
        state = self.state("part2_hall_exploration")
        self.assertFalse(self.episode(("Cipher Archive", None)).run_scene(state))
        self.assertTrue(state.flags["part2_cipher_archive"])
        self.assertEqual(state.scene, "part2_hall_exploration")
        self.assertEqual(state.play_minutes, 0)
        self.assertIn("Cipher Archive", " ".join(state.journal))

        state = self.saved_copy(state)
        menus = []
        self.assertFalse(self.episode(("Erased Statue", None), menus).run_scene(state))
        self.assertFalse(any("Cipher Archive" in option for _, options in menus for option in options))
        self.assertTrue(state.flags["part2_erased_statue"])
        self.assertEqual(len(state.journal), 2)
        self.assertEqual(state.play_minutes, 0)

        state = self.saved_copy(state)
        menus = []
        self.assertTrue(self.episode(("Dead Testimony", "Echo Bridge"), menus).run_scene(state))
        self.assertFalse(any("Erased Statue" in option for _, options in menus for option in options))
        self.assertTrue(state.flags["part2_testimony_first"])
        self.assertIn(QUEST_NAMES_LOST, state.quests)
        self.assertIn("first Warden testimony", " ".join(state.journal))
        self.assertEqual((state.scene, state.play_minutes), ("part2_echo_bridge", 14))

        uninterrupted = self.state("part2_hall_exploration")
        self.episode(("Cipher Archive", "Erased Statue", "Dead Testimony", "Echo Bridge")).run_scene(uninterrupted)
        self.assertEqual(state.to_dict(), uninterrupted.to_dict())

    def test_unanswered_testimony_is_a_visited_room_without_becoming_a_recovered_testimony(self):
        state = self.state("part2_hall_exploration")
        state.flags.pop("part2_spoke_road_name")
        self.assertFalse(self.episode(("Dead Testimony", None)).run_scene(state))
        state = self.saved_copy(state)
        menus = []
        self.assertTrue(self.episode(("Cipher Archive", "Echo Bridge"), menus).run_scene(state))

        self.assertTrue(state.flags["part2_hall_testimony_heard"])
        self.assertFalse(state.flags.get("part2_testimony_first", False))
        self.assertNotIn(QUEST_NAMES_LOST, state.quests)
        self.assertFalse(any("Dead Testimony" in option for _, options in menus for option in options))
        self.assertIn("testimony remained unanswered", " ".join(state.journal))
        self.assertEqual(state.play_minutes, 10)

    def test_calenor_truths_survive_reentry_and_are_available_in_the_journal(self):
        state = self.state("part2_calenor_reunion")
        self.assertFalse(self.episode(("Why hide", None)).run_scene(state))
        self.assertTrue(state.flags["part2_calenor_truth_hidden_name"])
        self.assertEqual(state.play_minutes, 0)
        self.assertIn("birth-name", " ".join(state.journal))
        state = self.saved_copy(state)

        menus = []
        self.assertFalse(self.episode(("What did Teren", None), menus).run_scene(state))
        self.assertFalse(any("Why hide" in option for _, options in menus for option in options))
        state = self.saved_copy(state)
        self.assertFalse(self.episode(("Why must the Rider", None)).run_scene(state))
        self.assertIn("distinct from my birth-name", " ".join(state.journal))
        state = self.saved_copy(state)
        menus = []
        self.assertTrue(self.episode(("Forgive Calenor",), menus).run_scene(state))
        self.assertFalse(any(heading == "ASK CALENOR THE THREE TRUTHS" for heading, _ in menus))
        self.assertEqual((state.scene, state.play_minutes), ("part2_vigil", 10))
        self.assertTrue(state.flags["part2_testimony_third"])
        self.assertEqual(len(state.journal), 4)

        uninterrupted = self.state("part2_calenor_reunion")
        self.episode(("Why hide", "What did Teren", "Why must the Rider", "Forgive Calenor")).run_scene(uninterrupted)
        self.assertEqual(state.to_dict(), uninterrupted.to_dict())

    def test_legacy_recovered_first_testimony_is_already_a_visited_hall_room(self):
        state = self.state("part2_hall_exploration")
        state.flags.update({"part2_testimony_first": True, "part2_cipher_archive": True})
        menus = []
        self.assertTrue(self.episode(("Echo Bridge",), menus).run_scene(state))
        self.assertFalse(any("Dead Testimony" in option for _, options in menus for option in options))
        self.assertEqual(state.play_minutes, 10)

    def test_lone_descent_records_actual_star_guidance_only_after_choices_are_committed(self):
        state = self.state("part2_descent")
        self.assertFalse(self.episode((None,)).run_scene(state))
        self.assertFalse(state.flags.get("part2_star_guided_descent", False))
        self.assertEqual(state.journal, [])

        self.assertTrue(self.episode(("Calenor's lesson", "Let the star-mark choose")).run_scene(state))

        self.assertTrue(state.flags["part2_star_guided_descent"])
        self.assertEqual(state.character.corruption, 1)
        state = self.saved_copy(state)
        self.assertTrue(state.flags["part2_star_guided_descent"])
        self.assertIn("let the star-mark choose my steps", " ".join(state.journal))

    def test_shadow_ending_recap_distinguishes_claiming_from_corruption_override(self):
        for label, hope, corruption, deliberate in (
            ("Claim the road", 10, 0, True),
            ("Renew the ancient seal", 0, 5, False),
        ):
            with self.subTest(choice=label):
                state = self.state("part2_seal_choice")
                state.character.hope = hope
                state.character.corruption = corruption
                self.assertTrue(self.episode((label,)).run_scene(state))
                self.assertEqual(state.ending, "shadows_name")
                state = self.saved_copy(state)
                recap = dict(part_two_ending_breakdown(state))["The Dead Road"]
                if deliberate:
                    self.assertIn("You claimed the road", recap)
                    self.assertNotIn("Corruption overrode", recap)
                else:
                    self.assertIn("Corruption overrode the attempt to renew", recap)

    def test_ritual_intent_is_acknowledged_saved_and_remembered_without_changing_ending(self):
        for choice, flag, acknowledgment, recap_text in (
            ("Calenor anchors", "part2_ritual_calenor_anchor", "failing spoke's weight", "asked Calenor to anchor"),
            ("Divide among", "part2_ritual_shared_voices", "freely offer", "company to share its voices"),
            ("Prepare the vault", "part2_ritual_collapse_prepared", "where to strike", "prepared the vault's fault-lines"),
        ):
            with self.subTest(choice=choice):
                state = self.state("part2_last_seal")
                output = []
                answers = iter((choice, "Reject the star"))

                def select(_heading, options):
                    target = next(answers)
                    return next(index + 1 for index, option in enumerate(options) if target in option)

                episode = PartTwoEpisode(
                    TerminalUI(color=False, fast=True, output_fn=output.append), select,
                    lambda *_: self.fail("Preparing the ritual must not start combat"),
                )
                self.assertTrue(episode.run_scene(state))
                self.assertEqual((state.character.hope, state.character.corruption, state.play_minutes), (1, 0, 6))
                self.assertIn(acknowledgment, " ".join(output))
                self.assertTrue(state.flags[flag])
                state = self.saved_copy(state)
                state.scene = "part2_seal_choice"
                self.assertTrue(self.episode(("Renew the ancient seal",)).run_scene(state))
                self.assertEqual(state.ending, "last_warden")
                self.assertIn(recap_text, dict(part_two_ending_breakdown(state))["The Dead Road"])

    def test_actual_save_and_main_menu_commands_resume_the_next_unfinished_hall_or_truth(self):
        for scene in ("part2_hall_exploration", "part2_calenor_reunion"):
            with self.subTest(scene=scene), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                answers = iter(("1", "s", "1", "m"))
                ui = TerminalUI(color=False, fast=True, input_fn=lambda _: next(answers), output_fn=lambda _: None)
                ui.supports_checkpoints = True
                game = Game(ui, saves=SaveManager(root))
                game.state = self.state(scene)

                self.assertFalse(game.part_two.run_scene(game.state))
                manual = game.saves.load(1)
                automatic = game.checkpoints.resume()
                self.assertEqual(manual.to_dict(), game.state.to_dict())
                self.assertEqual(automatic.to_dict(), manual.to_dict())
                self.assertEqual(len(manual.journal), 1)
                self.assertEqual(manual.play_minutes, 0)

                continuation = iter(("1", "1", "1"))
                resumed_ui = TerminalUI(color=False, fast=True, input_fn=lambda _: next(continuation), output_fn=lambda _: None)
                resumed = Game(resumed_ui, saves=SaveManager(root))
                resumed.state = manual
                self.assertTrue(resumed.part_two.run_scene(resumed.state))

                control = self.state(scene)
                if scene == "part2_hall_exploration":
                    labels = ("Cipher Archive", "Erased Statue", "Dead Testimony", "Echo Bridge")
                else:
                    labels = ("Why hide", "What did Teren", "Why must the Rider", "Forgive Calenor")
                self.episode(labels).run_scene(control)
                self.assertEqual(resumed.state.to_dict(), control.to_dict())

    def test_arrival_is_remembered_once_without_marking_future_stops_or_applying_a_choice(self):
        for scene in sorted(scene for scene in VALID_SCENE_IDS if scene.startswith("part2_")):
            with self.subTest(scene=scene):
                state = self.state(scene)
                before = state.to_dict()
                before["visited"] = [scene]
                self.assertFalse(self.episode((None,)).run_scene(state))
                self.assertEqual(state.to_dict(), before)
                state = self.saved_copy(state)
                self.assertFalse(self.episode((None,)).run_scene(state))
                self.assertEqual(state.to_dict(), before)

        invalid = self.state("part2_unknown_road")
        with self.assertRaises(ValueError):
            self.episode(()).run_scene(invalid)
        self.assertEqual(invalid.visited, [])


if __name__ == "__main__":
    unittest.main()
