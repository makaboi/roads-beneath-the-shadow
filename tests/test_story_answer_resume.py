"""Every submitted Part II answer survives a safe save or closed input."""

import random
import tempfile
import unittest
from pathlib import Path

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.content import ORIGINS, QUEST_PRISONERS_ASH, QUEST_REACH_CALENOR
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.ui import InputClosed, TerminalUI
from tests.helpers import VictoryCombat


# Labels describe player decisions, independently of their saved option IDs.
# Both ordinary and conditional menus are exercised, including all three
# Burning Memory questions and the prisoner route with no rescue follow-up.
CASES = (
    ("descent_lesson", "part2_descent", ("Calenor's lesson", "Trust her"), {}, (), {}),
    ("descent_mark", "part2_descent", ("turn your anger into power", "Demand obedience"), {}, (), {}),
    ("descent_tobin", "part2_descent", ("Anger at the secrets", "Trust him"), {"part_two_mara_present": False}, (), {}),
    ("descent_alone", "part2_descent", ("turn your anger into power", "Let the star-mark choose"), {"part_two_mara_present": False, "part_two_tobin_present": False}, (), {}),
    ("hall_mara", "part2_hall", ("hidden syllable", "Mara holds"), {}, (), {}),
    ("hall_tobin", "part2_hall", ("road-name", "Tobin holds"), {}, (), {}),
    ("hall_alone", "part2_hall", ("Refuse", "stand together"), {"part_two_mara_present": False, "part_two_tobin_present": False}, (), {}),
    ("bridge_hidden", "part2_echo_bridge", ("hidden Warden stair", "Hunt the sapper"), {"part_two_hidden_route_known": True}, (), {}),
    ("bridge_exposed", "part2_echo_bridge", ("exposed bridgehead", "Defend the ropes"), {}, (), {}),
    ("prisoner_locks", "part2_prisoners", ("Rescue the captives", "Pick the cage locks"), {}, (), {}),
    ("prisoner_sword", "part2_prisoners", ("Rescue the captives", "Break the rusted hinges"), {}, ("calenor_broken_sword",), {}),
    ("prisoner_drain", "part2_prisoners", ("Rescue the captives", "Open the Warden drain"), {}, (), {}),
    ("prisoner_wards", "part2_prisoners", ("Preserve the flood wards",), {}, (), {}),
    ("prisoner_onward", "part2_prisoners", ("Race onward",), {}, (), {}),
    ("troll_chain", "part2_chain_troll", ("Break the restraining chain", "Drain the Drowned Mile"), {}, (), {}),
    ("troll_wheel", "part2_chain_troll", ("Turn the flood wheel", "Preserve the Drowned Mile"), {}, (), {}),
    ("troll_preserve", "part2_chain_troll", ("Preserve the restraining chain", "Collapse the flooded branch"), {}, (), {}),
    ("house_share", "part2_house_under_ash", ("Share the forge truth", "Warden service passage"), {}, (), {}),
    ("house_alone", "part2_house_under_ash", ("Name the forge truth", "ruined dormitory"), {"part_two_mara_present": False}, (), {}),
    ("house_departure", "part2_house_under_ash", ("Keep moving", "child-height handprints"), {}, (), {"mara_trust": -1}),
    ("memory_rooms", "part2_burning_memory", ("Search every room", "Lift the board", "Take his hand"), {}, (), {}),
    ("memory_star", "part2_burning_memory", ("Ask the star-mark", "Call to her", "Ask why he knew"), {}, (), {}),
    ("memory_child", "part2_burning_memory", ("Follow the child-self", "Mark the place", "Look back"), {}, (), {}),
    ("teren_evidence", "part2_teren", ("Present the evidence", "Spare Teren"), {"part2_cipher_archive": True, "part2_erased_statue": True}, (), {}),
    ("teren_token", "part2_teren", ("Ranger token", "Bind Teren"), {"part2_testimony_first": True}, ("ranger_token",), {}),
    ("teren_attack", "part2_teren", ("Attack before", "Kill Teren"), {}, (), {}),
    ("calenor_sword", "part2_calenor_prison", ("broken sword", "Bring him home"), {}, ("calenor_broken_sword",), {}),
    ("calenor_star", "part2_calenor_prison", ("star-mark", "Demand why"), {}, (), {}),
    ("calenor_oath", "part2_calenor_prison", ("Warden oath", "Command him"), {"part2_testimony_first": True, "part2_testimony_second": True}, (), {}),
    ("seal_anchor", "part2_last_seal", ("Calenor anchors", "Bargain for enough"), {}, (), {}),
    ("seal_shared", "part2_last_seal", ("Divide among", "Reject the star"), {}, (), {}),
    ("seal_collapse", "part2_last_seal", ("Prepare the vault", "Reject the star"), {}, (), {}),
)


class StoryAnswerResumeTests(unittest.TestCase):
    @staticmethod
    def initial(case):
        name, scene, _answers, flags, items, attributes = case
        character = Character.from_origin("Éowen", ORIGINS[1])
        character.hp = 17
        character.focus = 2
        character.hope = 4
        character.corruption = 1
        character.mara_trust = 2
        character.tobin_trust = 3
        for item in items:
            character.add_item(item)
        for key, value in attributes.items():
            setattr(character, key, value)
        return GameState(
            character, journey_id=f"resume-{name}", chapter=2, scene=scene,
            flags={"part_two_mara_present": True, "part_two_tobin_present": True, **flags},
            quests=[QUEST_PRISONERS_ASH, QUEST_REACH_CALENOR],
            journal=["A traveler kept this clue before reaching the next question."],
            play_minutes=41,
        )

    @staticmethod
    def game(root, state, answers):
        ui = TerminalUI(
            color=False, fast=True, checkpoint_support=True,
            input_fn=lambda _: "1", output_fn=lambda _: None,
        )
        game = Game(ui, saves=SaveManager(root), rng=random.Random(51))
        game.state = state
        game.combat = VictoryCombat()
        remaining = iter(answers)
        prompts = []

        def choose(heading, options):
            prompts.append(heading)
            target = next(remaining)
            matches = [index for index, option in enumerate(options, 1) if target in option]
            if len(matches) != 1:
                raise AssertionError(f"Expected one choice matching {target!r}; got {options!r}")
            return matches[0]

        ui.choose_story = choose
        return game, prompts

    def test_every_answer_boundary_restores_the_entire_uninterrupted_scene_outcome(self):
        for case in CASES:
            name, _scene, answers, *_ = case
            with tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                control_state = self.initial(case)
                control, control_prompts = self.game(root / "control", control_state, answers)
                self.assertTrue(control.part_two.run_scene(control_state))
                expected = control_state.to_dict()
                self.assertFalse(any("_pending_" in flag for flag in expected["flags"]))

                for boundary in range(1, len(answers) + 1):
                    with self.subTest(case=name, boundary=boundary):
                        initial = self.initial(case)
                        character_before = initial.to_dict()["character"]
                        stopped, _ = self.game(root / f"stop-{boundary}", initial, answers)
                        recorded_answers = 0

                        def checkpoint_and_close():
                            nonlocal recorded_answers
                            recorded_answers += 1
                            stopped._record_checkpoint()
                            stopped.saves.save(1, stopped.state)
                            if recorded_answers == boundary:
                                raise InputClosed()

                        stopped.part_two.checkpoint = checkpoint_and_close
                        with self.assertRaises(InputClosed):
                            stopped.part_two.run_scene(initial)
                        self.assertEqual(initial.to_dict()["character"], character_before)
                        self.assertEqual(initial.play_minutes, 41)
                        self.assertEqual(stopped.combat.encounters, [])
                        manual = stopped.saves.load(1)
                        automatic = stopped.checkpoints.resume()
                        self.assertEqual(manual.to_dict(), initial.to_dict())
                        self.assertEqual(automatic.to_dict(), manual.to_dict())
                        self.assertEqual(manual.save_version, 2)

                        for mode, loaded in (("manual", manual), ("automatic", automatic)):
                            resumed, resumed_prompts = self.game(root / f"resume-{boundary}-{mode}", loaded, answers[boundary:])
                            self.assertTrue(resumed.part_two.run_scene(loaded))
                            self.assertEqual(resumed_prompts, control_prompts[boundary:])
                            self.assertEqual(loaded.to_dict(), expected)
                            self.assertEqual(resumed.combat.encounters, control.combat.encounters)

    def test_manual_save_at_the_following_question_keeps_the_answer_already_given(self):
        for case in CASES:
            name, _scene, answers, *_ = case
            if len(answers) < 2:
                continue
            with self.subTest(case=name), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                control_state = self.initial(case)
                control, control_prompts = self.game(root / "control", control_state, answers)
                self.assertTrue(control.part_two.run_scene(control_state))
                state = self.initial(case)
                stopped, _ = self.game(root / "stopped", state, answers)
                stages = iter((answers[0], "save", "menu"))

                def choose_then_save(_heading, options):
                    action = next(stages)
                    if action == "save":
                        return "s"
                    if action == "menu":
                        return "m"
                    return next(index for index, option in enumerate(options, 1) if action in option)

                stopped.ui.choose_story = choose_then_save
                self.assertFalse(stopped.part_two.run_scene(state))
                self.assertEqual(stopped.combat.encounters, [])
                manual = stopped.saves.load(1)
                self.assertEqual(manual.to_dict(), stopped.checkpoints.resume().to_dict())
                resumed, prompts = self.game(root / "resumed", manual, answers[1:])
                self.assertTrue(resumed.part_two.run_scene(manual))
                self.assertEqual(prompts, control_prompts[1:])
                self.assertEqual(manual.to_dict(), control_state.to_dict())
                self.assertEqual(resumed.combat.encounters, control.combat.encounters)

    def test_conditional_menu_reordering_keeps_the_saved_option_identity(self):
        cases = (
            (next(case for case in CASES if case[0] == "teren_attack"), "ranger_token", "part2_teren"),
            (next(case for case in CASES if case[0] == "calenor_oath"), "calenor_broken_sword", "part2_calenor_prison"),
        )
        for case, new_item, scene in cases:
            with self.subTest(scene=scene), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                original = self.initial(case)
                stopped, _ = self.game(root / "stopped", original, case[2])

                def checkpoint_and_close():
                    stopped._record_checkpoint()
                    raise InputClosed()

                stopped.part_two.checkpoint = checkpoint_and_close
                with self.assertRaises(InputClosed):
                    stopped.part_two.run_scene(original)
                loaded = stopped.checkpoints.resume()
                loaded.character.add_item(new_item)
                control_state = self.initial(case)
                control_state.character.add_item(new_item)
                control, _ = self.game(root / "control", control_state, case[2])
                self.assertTrue(control.part_two.run_scene(control_state))
                resumed, prompts = self.game(root / "resume", loaded, case[2][1:])
                self.assertTrue(resumed.part_two.run_scene(loaded))
                self.assertEqual(len(prompts), 1)
                self.assertEqual(loaded.to_dict(), control_state.to_dict())
                self.assertEqual(resumed.combat.encounters, control.combat.encounters)

    def test_damaged_pending_answers_cannot_replace_or_load_as_a_usable_save(self):
        invalid_cases = (
            ("part2_descent", {"part2_descent_pending_carried_lesson": True, "part2_descent_pending_carried_mark": True}),
            ("part2_descent", {"part2_hall_pending_name_road_name": True}),
            ("part2_descent", {"part2_descent_pending_carried_invented": True}),
            ("part2_descent", {"part2_descent_pending_rear_trust": True}),
            ("part2_hall", {"part2_hall_pending_name_road_name": True, "part2_hall_pending_holder_mara": True, "part_two_mara_present": False}),
            ("part2_echo_bridge", {"part2_echo_bridge_pending_approach_stair": True}),
            ("part2_prisoners", {"part2_prisoners_pending_priority_wards": True, "part2_prisoners_pending_rescue_locks": True}),
            ("part2_teren", {"part2_teren_pending_approach_token": True}),
            ("part2_calenor_prison", {"part2_calenor_prison_pending_method_sword": True}),
            ("part2_calenor_prison", {"part2_calenor_prison_pending_method_oath": True}),
        )
        for scene, flags in invalid_cases:
            with self.subTest(scene=scene, flags=flags), tempfile.TemporaryDirectory() as temporary:
                saves = SaveManager(Path(temporary))
                good = GameState(Character.from_origin("Éowen", ORIGINS[1]), chapter=2, scene=scene)
                saves.save(1, good)
                original_bytes = saves._path(1).read_bytes()
                good.flags = flags
                with self.assertRaisesRegex(ValueError, "pending story answer"):
                    saves.save(1, good)
                self.assertEqual(saves._path(1).read_bytes(), original_bytes)
                import json

                saves._path(2).write_text(json.dumps({"state": good.to_dict()}), encoding="utf-8")
                self.assertTrue(saves.slot_metadata(2)["corrupt"])
                self.assertEqual(saves.load(1).scene, scene)


if __name__ == "__main__":
    unittest.main()
