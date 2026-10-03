import tempfile
from pathlib import Path
import unittest

from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.part_two import PartTwoEpisode, part_two_ending_breakdown
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.ui import TerminalUI


class VigilTests(unittest.TestCase):
    def state(self, **flags) -> GameState:
        return GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            scene="part2_vigil",
            chapter=2,
            play_minutes=90,
            flags={"part_two_mara_present": True, "part_two_tobin_present": True, **flags},
        )

    def episode(self, labels, *, output=None, menus=None, screen_reader=False) -> PartTwoEpisode:
        answers = iter(labels)

        def choose(heading, options):
            if menus is not None:
                menus.append((heading, tuple(options)))
            label = next(answers)
            if label is None:
                return None
            for index, option in enumerate(options, 1):
                if label in option:
                    return index
            raise AssertionError(f"{label!r} was not offered in {heading}: {options}")

        return PartTwoEpisode(
            TerminalUI(
                color=False,
                fast=True,
                screen_reader=screen_reader,
                output_fn=output.append if output is not None else lambda _: None,
            ),
            choose,
            lambda *_: self.fail("The vigil must not start combat"),
        )

    def test_optional_vigil_can_be_skipped_without_a_reward_or_time_cost(self) -> None:
        state = self.state()
        before = state.to_dict()
        before["visited"] = ["part2_vigil"]
        self.assertTrue(self.episode(("Enter the Last Seal",)).run_scene(state))
        before["scene"] = "part2_last_seal"
        self.assertEqual(state.to_dict(), before)

    def test_exiting_at_either_menu_does_not_apply_an_unfinished_conversation(self) -> None:
        for labels in ((None,), ("Speak with Mara", None), ("Help Tobin", None), ("Sit beside Calenor", None)):
            with self.subTest(labels=labels):
                state = self.state()
                before = state.to_dict()
                before["visited"] = ["part2_vigil"]
                self.assertFalse(self.episode(labels).run_scene(state))
                self.assertEqual(state.to_dict(), before)

    def test_completed_conversation_survives_save_and_is_not_offered_again(self) -> None:
        state = self.state()
        self.assertFalse(self.episode(("Speak with Mara", "Ask what she wants", None)).run_scene(state))
        self.assertEqual((state.character.mara_trust, state.play_minutes), (1, 92))
        self.assertTrue(state.flags["part2_vigil_mara"])
        with tempfile.TemporaryDirectory() as directory:
            saves = SaveManager(Path(directory))
            saves.save(1, state)
            resumed = saves.load(1)
        menus = []
        self.assertTrue(self.episode(("Help Tobin", "Promise to bring", "Enter the Last Seal"), menus=menus).run_scene(resumed))
        self.assertNotIn("Speak with Mara", " ".join(menus[0][1]))
        self.assertEqual((resumed.character.mara_trust, resumed.character.tobin_trust, resumed.play_minutes), (1, 1, 94))
        self.assertEqual(len(resumed.journal), 2)

    def test_each_conversation_is_available_once_and_completion_adds_six_minutes(self) -> None:
        state = self.state()
        self.assertTrue(self.episode((
            "Speak with Mara", "Ask what she wants",
            "Help Tobin", "Promise to bring",
            "Sit beside Calenor", "Ask for a memory",
            "Enter the Last Seal",
        )).run_scene(state))
        self.assertEqual((state.play_minutes, state.character.hope), (96, 1))
        self.assertEqual((state.character.mara_trust, state.character.tobin_trust), (1, 1))
        self.assertEqual(len(state.journal), 3)
        state.scene = "part2_vigil"
        menus = []
        before = state.to_dict()
        self.assertTrue(self.episode(("Enter the Last Seal",), menus=menus).run_scene(state))
        self.assertEqual(menus[0][1], ("Enter the Last Seal",))
        before["scene"] = "part2_last_seal"
        self.assertEqual(state.to_dict(), before)

    def test_missing_companions_have_no_conversation_or_trust_reward(self) -> None:
        for mara, tobin in ((False, False), (False, True), (True, False)):
            with self.subTest(mara=mara, tobin=tobin):
                state = self.state(part_two_mara_present=mara, part_two_tobin_present=tobin)
                menus = []
                self.assertTrue(self.episode(("Enter the Last Seal",), menus=menus).run_scene(state))
                options = " ".join(menus[0][1])
                self.assertEqual("Speak with Mara" in options, mara)
                self.assertEqual("Help Tobin" in options, tobin)
                self.assertEqual((state.character.mara_trust, state.character.tobin_trust), (0, 0))

    def test_tobins_memory_reflects_neds_actual_fate(self) -> None:
        for flags, expected, excluded in (
            ({"part_two_neds_watch_continues": True}, "He kept the light anyway", "Ned owes me a breakfast"),
            ({"part_two_ned_safe": True}, "Ned owes me a breakfast", "He was frightened"),
            ({}, "somebody else's trouble", "Ned's watch-whistle"),
        ):
            with self.subTest(flags=flags):
                output = []
                state = self.state(**flags)
                self.assertTrue(self.episode(("Help Tobin", "Help him mend", "Enter the Last Seal"), output=output).run_scene(state))
                transcript = " ".join(output)
                self.assertIn(expected, transcript)
                self.assertNotIn(excluded, transcript)

    def test_mara_remembers_the_shared_past_only_when_it_happened(self) -> None:
        for shared in (False, True):
            with self.subTest(shared=shared):
                output = []
                state = self.state(shared_past_with_mara=shared)
                self.assertTrue(self.episode(("Speak with Mara", "Tell her she owes", "Enter the Last Seal"), output=output).run_scene(state))
                self.assertEqual("guarded ember in Midgewater" in " ".join(output), shared)

    def test_calenor_conversation_does_not_erase_condemnation_or_force_forgiveness(self) -> None:
        state = self.state(part2_calenor_condemned=True)
        self.assertTrue(self.episode(("Sit beside Calenor", "Tell him trust", "Enter the Last Seal")).run_scene(state))
        self.assertTrue(state.flags["part2_calenor_condemned"])
        self.assertTrue(state.flags["part2_calenor_trust_rebuild"])
        self.assertEqual(state.character.hope, 0)

    def test_every_response_has_a_distinct_recorded_outcome(self) -> None:
        cases = (
            ("Speak with Mara", "Ask what she wants", "part2_mara_future_named", "a future she would build"),
            ("Speak with Mara", "Tell her she owes", "part2_mara_oath_free", "owing the road no oath"),
            ("Speak with Mara", "Ask for one more", "part2_mara_last_battle", "one more battle, rather than a lifetime"),
            ("Help Tobin", "Promise to bring", "part2_tobin_home_promised", "watch's people and stories home"),
            ("Help Tobin", "Ask what Bree", "part2_tobin_bree_remembered", "he remembered Bree at sunrise"),
            ("Help Tobin", "Help him mend", "part2_tobin_light_shared", "mended the last lantern together"),
            ("Sit beside Calenor", "Ask for a memory", "part2_calenor_memory_shared", "ordinary memory beyond his Warden duty"),
            ("Sit beside Calenor", "Tell him trust", "part2_calenor_trust_rebuild", "earn trust one honest day"),
            ("Sit beside Calenor", "Sit beside him", "part2_calenor_silence_shared", "without giving an answer"),
        )
        for topic, response, flag, expected_recap in cases:
            with self.subTest(response=response):
                state = self.state()
                self.assertTrue(self.episode((topic, response, "Enter the Last Seal")).run_scene(state))
                self.assertTrue(state.flags[flag])
                self.assertEqual(state.play_minutes, 92)
                self.assertEqual(len(state.journal), 1)
                state.ending = "last_warden"
                recap = " ".join(text for _, text in part_two_ending_breakdown(state))
                self.assertIn(expected_recap, recap)

    def test_lantern_art_has_an_accessible_description(self) -> None:
        output = []
        self.assertTrue(self.episode(("Enter the Last Seal",), output=output, screen_reader=True).run_scene(self.state()))
        self.assertIn("[Scene: A single lantern hangs beneath a low stone arch above three steps into darkness.]", output)

    def test_shadow_payoff_does_not_claim_the_promises_came_true(self) -> None:
        state = self.state(part2_vigil_mara=True, part2_mara_future_named=True)
        output = []
        self.episode((), output=output)._vigil_payoff(state, "shadows_name")
        transcript = " ".join(output)
        self.assertIn("voices it has borrowed", transcript)
        self.assertNotIn("Something she will build herself", transcript)

    def test_calenors_memory_payoff_distinguishes_escape_from_sacrifice(self) -> None:
        for escaped in (False, True):
            with self.subTest(escaped=escaped):
                state = self.state(part2_calenor_memory_shared=True, part2_calenor_escaped=escaped)
                output = []
                self.episode((), output=output)._vigil_payoff(state, "living_road" if escaped else "last_warden")
                transcript = " ".join(output)
                self.assertEqual("Calenor asks whether" in transcript, escaped)
                self.assertEqual("You carry a winter kitchen" in transcript, not escaped)

    def test_descent_addresses_only_a_present_companion(self) -> None:
        for mara, tobin, heading in (
            (True, True, "MARA HEARS THE RIDER ABOVE"),
            (False, True, "TOBIN HEARS THE RIDER ABOVE"),
            (False, False, "THE RIDER FOLLOWS YOUR FOOTSTEPS"),
        ):
            with self.subTest(mara=mara, tobin=tobin):
                state = self.state(part_two_mara_present=mara, part_two_tobin_present=tobin)
                state.scene = "part2_descent"
                menus = []
                labels = ("Calenor's lesson", "Trust" if mara or tobin else "Hold Calenor's broken sword")
                self.assertTrue(self.episode(labels, menus=menus).run_scene(state))
                self.assertEqual(menus[-1][0], heading)
                self.assertEqual((state.character.mara_trust, state.character.tobin_trust), (int(mara), int(tobin and not mara)))

    def test_ruined_road_memory_matches_who_escaped_the_seal(self) -> None:
        for flags, escaped in (
            ({"part2_teren_spared": True}, True),
            ({"part2_teren_spared": True, "part2_teren_took_spoke": True}, True),
            ({"part2_teren_spared": True, "part2_calenor_rebound": True}, False),
            ({}, False),
        ):
            with self.subTest(flags=flags):
                state = self.state(part2_calenor_memory_shared=True, **flags)
                state.scene = "part2_seal_choice"
                output = []
                self.assertTrue(self.episode(("Destroy the Dead Road",), output=output).run_scene(state))
                self.assertEqual((state.scene, state.ending), ("complete", "road_in_ruin"))
                self.assertEqual(state.flags.get("part2_calenor_escaped", False), escaped)
                transcript = " ".join(output)
                self.assertEqual("Calenor asks whether you still blame the pan" in transcript, escaped)
                self.assertEqual("a Warden's last words" in transcript, not escaped)
                if escaped:
                    self.assertRegex(
                        dict(part_two_ending_breakdown(state))["Calenor and Teren"],
                        r"Calenor (escaped|left the spoke alive)",
                    )

    def test_descent_corruption_requires_accepting_the_marks_power(self) -> None:
        for choice, answer_id, flag, corruption, memory in (
            ("Anger at the secrets", "anger", "part2_descent_anger", 2, "You have a right to be angry"),
            ("Let the star-mark turn", "mark", "part2_descent_mark_bargain", 3, "Let the words be mine"),
        ):
            with self.subTest(choice=choice):
                state = self.state()
                state.scene = "part2_descent"
                state.character.corruption = 2
                before = state.to_dict()
                before["visited"] = ["part2_descent"]
                self.assertFalse(self.episode((choice, None)).run_scene(state))
                before["flags"][f"part2_descent_pending_carried_{answer_id}"] = True
                self.assertEqual(state.to_dict(), before)
                with tempfile.TemporaryDirectory() as directory:
                    saves = SaveManager(Path(directory))
                    saves.save(1, state)
                    state = saves.load(1)
                menus = []
                self.assertTrue(self.episode(("Warn her",), menus=menus).run_scene(state))
                self.assertEqual(len(menus), 1)
                self.assertFalse(any("_pending_" in key for key in state.flags))
                self.assertEqual(state.character.corruption, corruption)
                self.assertTrue(state.flags[flag])
                self.assertEqual(len(state.journal), 1)
                with tempfile.TemporaryDirectory() as directory:
                    saves = SaveManager(Path(directory))
                    saves.save(1, state)
                    state = saves.load(1)
                state.scene = "part2_calenor_reunion"
                output = []
                self.assertTrue(self.episode(("Why hide", "What did Teren", "Why must the Rider", "Condemn"), output=output).run_scene(state))
                self.assertIn(memory, " ".join(output))
                self.assertTrue(state.flags["part2_calenor_condemned"])
                self.assertEqual(state.character.corruption, corruption)

    def test_the_selected_childhood_lesson_returns_in_descent_and_reunion(self) -> None:
        for flag, lesson in (
            ("lesson_kindness", "kindness can find the darkest road"),
            ("lesson_tracking", "read the ground first, then read the sky"),
            ("lesson_courage", "fear is a warning, not your master"),
        ):
            with self.subTest(lesson=lesson):
                state = self.state(**{flag: True})
                state.scene = "part2_descent"
                menus = []
                self.assertTrue(self.episode(("Calenor's lesson", "Trust"), menus=menus).run_scene(state))
                self.assertEqual(menus[0][1][0], "Calenor's lesson: " + lesson)
                state.scene = "part2_calenor_reunion"
                output = []
                self.assertTrue(self.episode(("Why hide", "What did Teren", "Why must the Rider", "Forgive"), output=output).run_scene(state))
                transcript = " ".join(output).lower()
                if flag == "lesson_kindness":
                    self.assertIn("no road was too dark for kindness", transcript)
                else:
                    self.assertIn(lesson, transcript)


if __name__ == "__main__":
    unittest.main()
