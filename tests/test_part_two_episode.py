import unittest

from roads_beneath_shadow import part_two_artwork as part_two_art
from roads_beneath_shadow.app import Game
from roads_beneath_shadow.combat import CombatResult
from roads_beneath_shadow.content import (
    ORIGINS,
    QUEST_DEAD_ROAD_FATE,
    QUEST_EIGHTH_NAME,
    QUEST_LAST_SEAL,
    QUEST_NAMES_LOST,
    QUEST_PRISONERS_ASH,
    QUEST_REACH_CALENOR,
)
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.part_two import (
    PartTwoEpisode,
    part_two_ending,
    part_two_ending_breakdown,
)
from roads_beneath_shadow.ui import Color, TerminalUI
from tests.helpers import PartTwoPlayer, VictoryCombat


class RecordingCombat:
    def __init__(self, result: CombatResult = CombatResult.VICTORY) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def __call__(self, _state, enemies, config):
        self.calls.append({"enemies": enemies, "config": config})
        return self.result


class ArtRecordingUI(TerminalUI):
    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.art_calls: list[tuple[str, str, str | None]] = []
        self._art_depth = 0

    def art(self, text, color=Color.SILVER, *, alt_text=None) -> None:
        if self._art_depth == 0:
            self.art_calls.append((text, color, alt_text))
        self._art_depth += 1
        try:
            super().art(text, color, alt_text=alt_text)
        finally:
            self._art_depth -= 1


def label_choices(*targets):
    answers = iter(targets)

    def choose(_heading, options):
        target = next(answers)
        if target is None:
            return None
        return next(index for index, option in enumerate(options, 1) if target in option)

    return choose


class PartTwoEpisodeTestCase(unittest.TestCase):
    @staticmethod
    def _episode(choose, combat=None, output=None) -> PartTwoEpisode:
        return PartTwoEpisode(
            TerminalUI(
                color=False,
                fast=True,
                output_fn=output.append if output is not None else lambda _line: None,
            ),
            choose,
            combat or RecordingCombat(),
        )

    @staticmethod
    def _state(
        scene: str,
        *,
        flags: dict[str, bool] | None = None,
        quests: list[str] | None = None,
        play_minutes: int = 0,
    ) -> GameState:
        return GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            scene=scene,
            chapter=2,
            flags=dict(flags or {}),
            quests=list(quests or []),
            play_minutes=play_minutes,
        )


class PartTwoEpisodeTests(PartTwoEpisodeTestCase):
    def test_pursuit_uses_four_round_objective_without_wounding_rider(self) -> None:
        calls = []

        def combat(_state, enemies, config):
            calls.append((enemies, config))
            return CombatResult.VICTORY

        episode = PartTwoEpisode(
            TerminalUI(color=False, fast=True, output_fn=lambda _line: None),
            lambda _heading, _options: 1,
            combat,
        )
        state = GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            scene="part2_pursuit",
            chapter=2,
            flags={"part_two_mara_present": True, "part_two_tobin_present": True},
        )

        self.assertTrue(episode.run_scene(state))

        enemies, config = calls[0]
        self.assertEqual(len(enemies), 1)
        self.assertEqual((enemies[0].name, enemies[0].hp), ("Black Rider", 999))
        self.assertEqual((enemies[0].attack_min, enemies[0].attack_max), (2, 4))
        self.assertEqual(config.max_rounds, 4)
        self.assertFalse(config.surprise_round)
        self.assertTrue(config.objective_enemy_invulnerable)
        self.assertTrue(config.mara_aid)
        self.assertTrue(config.tobin_aid)
        self.assertEqual((state.scene, state.play_minutes), ("part2_hall", 7))

    def test_pursuit_star_command_costs_corruption_and_reduces_both_attacks(self) -> None:
        combat = RecordingCombat()
        episode = self._episode(label_choices("star-mark"), combat)
        state = self._state(
            "part2_pursuit",
            flags={"part_two_mara_present": False, "part_two_tobin_present": False},
        )

        self.assertTrue(episode.run_scene(state))

        rider = combat.calls[0]["enemies"][0]
        config = combat.calls[0]["config"]
        self.assertEqual((rider.attack_min, rider.attack_max, rider.hp), (1, 3, 999))
        self.assertEqual(state.character.corruption, 1)
        self.assertTrue(state.flags["part2_star_commanded"])
        self.assertNotIn("star_key", state.character.inventory)
        self.assertFalse(config.surprise_round)

    def test_pursuit_defeat_is_honest_and_continues_at_one_health(self) -> None:
        output: list[str] = []
        combat = RecordingCombat(CombatResult.DEFEAT)
        episode = self._episode(label_choices("broken sword"), combat, output)
        state = self._state("part2_pursuit")
        state.character.hp = 0

        self.assertTrue(episode.run_scene(state))

        self.assertEqual((state.character.hp, state.character.corruption), (1, 1))
        self.assertEqual(state.scene, "part2_hall")
        transcript = "\n".join(output).lower()
        self.assertIn("rider enters the hall", transcript)
        self.assertNotIn("rider falls", transcript)
        self.assertNotIn("rider is defeated", transcript)

    def test_real_journey_crosses_descent_and_pursuit_then_exits_hall(self) -> None:
        answers = iter(("1", "1", "1", "m"))
        output: list[str] = []
        game = Game(
            TerminalUI(
                color=False,
                fast=True,
                input_fn=lambda _prompt: next(answers),
                output_fn=output.append,
            )
        )
        game.state = self._state(
            "part2_descent",
            flags={"part_two_mara_present": True, "part_two_tobin_present": True},
        )
        combat = VictoryCombat()
        game.combat = combat

        game._run_journey()

        transcript = "\n".join(output)
        self.assertEqual(game.state.scene, "part2_hall")
        self.assertEqual(len(combat.encounters), 1)
        self.assertIn("THE HALL ASKS FOR A NAME", transcript)
        self.assertNotIn("Unknown scene", transcript)

    def test_hall_collects_both_answers_before_mutating(self) -> None:
        state = self._state(
            "part2_hall",
            flags={"part_two_mara_present": True, "part_two_tobin_present": True},
            play_minutes=13,
        )
        state.character.hope = 2
        state.character.corruption = 3
        state.character.mara_trust = 4
        before = state.to_dict()
        episode = self._episode(label_choices("road-name", None))

        self.assertFalse(episode.run_scene(state))

        self.assertEqual(state.to_dict(), before)

    def test_hall_name_effects_are_distinct_and_companion_options_require_presence(self) -> None:
        cases = (
            ("Refuse", None, 2, 0),
            ("road-name", "part2_spoke_road_name", 1, 0),
            ("hidden syllable", "part2_spoke_hidden_name", 1, 1),
        )
        for name_target, flag, hope, corruption in cases:
            with self.subTest(name_target=name_target):
                seen_options = []
                answers = iter((name_target, "stand together"))

                def choose(_heading, options):
                    seen_options.append(tuple(options))
                    target = next(answers)
                    return next(i for i, option in enumerate(options, 1) if target in option)

                state = self._state(
                    "part2_hall",
                    flags={"part_two_mara_present": False, "part_two_tobin_present": False},
                )

                self.assertTrue(self._episode(choose).run_scene(state))

                if flag is not None:
                    self.assertTrue(state.flags[flag])
                self.assertEqual((state.character.hope, state.character.corruption), (hope, corruption))
                self.assertEqual(len(seen_options[1]), 1)
                self.assertNotIn("Mara", seen_options[1][0])
                self.assertNotIn("Tobin", seen_options[1][0])
                self.assertEqual((state.scene, state.play_minutes), ("part2_hall_exploration", 5))

    def test_hall_can_entrust_the_dark_only_to_a_present_companion(self) -> None:
        captured: list[tuple[str, ...]] = []

        def choose(heading, options):
            captured.append(tuple(options))
            if heading == "THE HALL ASKS FOR A NAME":
                return 2
            return next(i for i, option in enumerate(options, 1) if "Mara" in option)

        state = self._state(
            "part2_hall",
            flags={"part_two_mara_present": True, "part_two_tobin_present": False},
        )

        self.assertTrue(self._episode(choose).run_scene(state))

        self.assertEqual(state.character.mara_trust, 1)
        self.assertEqual(state.character.tobin_trust, 0)
        self.assertTrue(any("Mara" in option for option in captured[1]))
        self.assertFalse(any("Tobin" in option for option in captured[1]))

    def test_dead_testimony_answers_only_the_spoken_road_name(self) -> None:
        cases = (
            ("Refuse", False),
            ("road-name", True),
            ("hidden syllable", False),
        )
        for name_target, testimony_answers in cases:
            with self.subTest(name_target=name_target):
                output: list[str] = []
                episode = self._episode(
                    label_choices(
                        name_target,
                        "stand together",
                        "Dead Testimony",
                        "Cipher Archive",
                        "Take the road to Echo Bridge",
                    ),
                    output=output,
                )
                state = self._state("part2_hall")

                self.assertTrue(episode.run_scene(state))
                self.assertTrue(episode.run_scene(state))

                self.assertEqual(
                    state.flags.get("part2_testimony_first", False),
                    testimony_answers,
                )
                self.assertEqual(QUEST_NAMES_LOST in state.quests, testimony_answers)
                transcript = "\n".join(output)
                if testimony_answers:
                    self.assertIn("We kept no crown", transcript)
                else:
                    self.assertIn("testimony remains unanswered", transcript)

    def test_hall_exploration_exit_does_not_bank_partial_rewards(self) -> None:
        for targets in (
            ("Cipher Archive", None),
            ("Cipher Archive", "Erased Statue", None),
        ):
            with self.subTest(targets=targets):
                state = self._state("part2_hall_exploration", play_minutes=19)
                before = state.to_dict()

                self.assertFalse(self._episode(label_choices(*targets)).run_scene(state))

                self.assertEqual(state.to_dict(), before)

    def test_hall_exploration_all_three_chambers_adds_only_four_optional_minutes(self) -> None:
        episode = self._episode(
            label_choices(
                "Cipher Archive",
                "Erased Statue",
                "Dead Testimony",
                "Take the road to Echo Bridge",
            )
        )
        state = self._state(
            "part2_hall_exploration",
            flags={"part2_spoke_road_name": True},
            play_minutes=20,
        )

        self.assertTrue(episode.run_scene(state))

        self.assertTrue(state.flags["part2_cipher_archive"])
        self.assertTrue(state.flags["part2_erased_statue"])
        self.assertTrue(state.flags["part2_testimony_first"])
        self.assertIn(QUEST_NAMES_LOST, state.quests)
        self.assertEqual((state.scene, state.play_minutes), ("part2_echo_bridge", 34))

    def test_hall_exploration_can_leave_after_two_without_false_testimony(self) -> None:
        episode = self._episode(
            label_choices("Cipher Archive", "Erased Statue", "Take the road to Echo Bridge")
        )
        state = self._state("part2_hall_exploration")

        self.assertTrue(episode.run_scene(state))

        self.assertFalse(state.flags.get("part2_testimony_first", False))
        self.assertNotIn(QUEST_NAMES_LOST, state.quests)
        self.assertEqual(state.play_minutes, 10)

    def test_hidden_route_knowledge_alone_does_not_create_bridge_flank(self) -> None:
        combat = RecordingCombat()
        state = self._state(
            "part2_echo_bridge",
            flags={"part_two_hidden_route_known": True},
        )

        self.assertTrue(
            self._episode(label_choices("exposed bridgehead", "Defend the ropes"), combat).run_scene(state)
        )

        config = combat.calls[0]["config"]
        self.assertFalse(config.surprise_round)
        self.assertIsNone(config.max_rounds)
        self.assertEqual(state.character.hope, 1)

    def test_warden_stair_sets_flank_wounds_same_sapper_and_grants_testimony(self) -> None:
        combat = RecordingCombat()
        state = self._state(
            "part2_echo_bridge",
            flags={"part_two_hidden_route_known": True},
        )

        self.assertTrue(
            self._episode(label_choices("Warden stair", "Hunt the sapper"), combat).run_scene(state)
        )

        enemies = combat.calls[0]["enemies"]
        config = combat.calls[0]["config"]
        self.assertEqual([enemy.archetype for enemy in enemies], ["saboteur", "commander", "archer"])
        self.assertLess(enemies[0].hp, enemies[0].max_hp)
        self.assertTrue(config.surprise_round)
        self.assertTrue(state.flags["part2_testimony_first"])
        self.assertIn(QUEST_NAMES_LOST, state.quests)
        self.assertEqual((state.scene, state.play_minutes), ("part2_drowned_mile", 8))

    def test_echo_bridge_defeat_does_not_claim_the_ropes_were_saved(self) -> None:
        output: list[str] = []
        combat = RecordingCombat(CombatResult.DEFEAT)
        state = self._state("part2_echo_bridge")
        state.character.hp = 0

        self.assertTrue(
            self._episode(
                label_choices("exposed bridgehead", "Defend the ropes"), combat, output
            ).run_scene(state)
        )

        self.assertEqual((state.character.hp, state.character.corruption), (1, 1))
        self.assertNotIn("bridge is saved", "\n".join(output).lower())

    def test_drowned_mile_collects_priority_before_opening_quest(self) -> None:
        state = self._state("part2_drowned_mile", play_minutes=21)
        before = state.to_dict()

        self.assertFalse(
            self._episode(label_choices(None)).run_scene(state)
        )
        self.assertEqual(state.to_dict(), before)

        self.assertTrue(
            self._episode(label_choices("Reach Calenor")).run_scene(state)
        )
        self.assertFalse(state.flags.get("part2_prisoners_rescued", False))
        self.assertIn(QUEST_PRISONERS_ASH, state.quests)
        self.assertEqual((state.scene, state.play_minutes), ("part2_prisoners", 26))

        wards_state = self._state("part2_drowned_mile")
        self.assertTrue(
            self._episode(label_choices("flood wards")).run_scene(wards_state)
        )
        self.assertEqual((wards_state.scene, wards_state.play_minutes), ("part2_prisoners", 5))

    def test_prisoner_rescue_is_atomic_and_updates_only_present_companions(self) -> None:
        state = self._state(
            "part2_prisoners",
            flags={"part_two_mara_present": True, "part_two_tobin_present": False},
            quests=[QUEST_PRISONERS_ASH],
            play_minutes=30,
        )
        state.character.mara_trust = 2
        state.character.tobin_trust = 5
        before = state.to_dict()

        self.assertFalse(
            self._episode(label_choices("Rescue the captives", None)).run_scene(state)
        )
        self.assertEqual(state.to_dict(), before)

        self.assertTrue(
            self._episode(label_choices("Rescue the captives", "Pick the cage locks")).run_scene(state)
        )
        self.assertTrue(state.flags["part2_prisoners_rescued"])
        self.assertIn(QUEST_PRISONERS_ASH, state.completed_quests)
        self.assertNotIn(QUEST_PRISONERS_ASH, state.quests)
        self.assertEqual((state.character.hope, state.character.mara_trust), (1, 3))
        self.assertEqual(state.character.tobin_trust, 5)
        self.assertEqual((state.scene, state.play_minutes), ("part2_chain_troll", 44))

    def test_prisoner_rescue_rewards_each_present_companion_once(self) -> None:
        state = self._state(
            "part2_prisoners",
            flags={"part_two_mara_present": True, "part_two_tobin_present": True},
            quests=[QUEST_PRISONERS_ASH],
        )

        self.assertTrue(
            self._episode(label_choices("Rescue the captives", "Pick the cage locks")).run_scene(state)
        )

        self.assertEqual((state.character.mara_trust, state.character.tobin_trust), (1, 1))

    def test_prisoner_bypass_keeps_quest_open_and_penalizes_only_present_companions(self) -> None:
        state = self._state(
            "part2_prisoners",
            flags={"part_two_mara_present": False, "part_two_tobin_present": True},
            quests=[QUEST_PRISONERS_ASH],
        )
        state.character.mara_trust = 4
        state.character.tobin_trust = 3

        self.assertTrue(self._episode(label_choices("Race onward")).run_scene(state))

        self.assertTrue(state.flags["part2_kept_initiative"])
        self.assertEqual((state.character.mara_trust, state.character.tobin_trust), (4, 2))
        self.assertIn(QUEST_PRISONERS_ASH, state.quests)
        self.assertNotIn(QUEST_PRISONERS_ASH, state.completed_quests)
        self.assertEqual(state.play_minutes, 10)

    def test_preserving_flood_wards_keeps_prisoner_quest_unresolved(self) -> None:
        state = self._state(
            "part2_prisoners",
            quests=[QUEST_PRISONERS_ASH],
        )

        self.assertTrue(self._episode(label_choices("Preserve the flood wards")).run_scene(state))

        self.assertTrue(state.flags["part2_flood_wards_preserved"])
        self.assertIn(QUEST_PRISONERS_ASH, state.quests)
        self.assertNotIn(QUEST_PRISONERS_ASH, state.completed_quests)

    def test_chain_troll_tactics_mutate_one_fresh_troll_and_use_real_initiative(self) -> None:
        cases = (
            ("Break the restraining chain", {}, (30, 1, 5, 9), False),
            ("Turn the flood wheel", {}, (24, 3, 5, 9), False),
            (
                "Preserve the restraining chain",
                {"part2_kept_initiative": True},
                (30, 3, 4, 8),
                True,
            ),
        )
        seen = []
        for target, flags, expected, surprise in cases:
            with self.subTest(target=target):
                combat = RecordingCombat()
                state = self._state("part2_chain_troll", flags=flags)

                self.assertTrue(
                    self._episode(
                        label_choices(target, "Drain the Drowned Mile"),
                        combat,
                    ).run_scene(state)
                )

                troll = combat.calls[0]["enemies"][0]
                config = combat.calls[0]["config"]
                seen.append(troll)
                self.assertEqual(
                    (troll.hp, troll.armor, troll.attack_min, troll.attack_max),
                    expected,
                )
                self.assertEqual(config.surprise_round, surprise)
                self.assertIsNone(config.max_rounds)
                self.assertTrue(state.flags["part2_testimony_second"])
                self.assertEqual((state.scene, state.play_minutes), ("part2_house_under_ash", 9))
        self.assertEqual(len({id(troll) for troll in seen}), 3)

    def test_chain_troll_flood_choice_is_atomic_before_combat(self) -> None:
        combat = RecordingCombat()
        state = self._state(
            "part2_chain_troll",
            flags={"part2_kept_initiative": True},
            play_minutes=41,
        )
        before = state.to_dict()

        self.assertFalse(
            self._episode(
                label_choices("Break the restraining chain", None),
                combat,
            ).run_scene(state)
        )

        self.assertEqual(state.to_dict(), before)
        self.assertEqual(combat.calls, [])

    def test_chain_troll_applies_each_post_battle_flood_outcome(self) -> None:
        cases = (
            (
                "Drain the Drowned Mile",
                1,
                False,
                False,
            ),
            (
                "Preserve the Drowned Mile's ancient wards",
                0,
                True,
                False,
            ),
            (
                "Collapse the flooded branch",
                0,
                False,
                True,
            ),
        )
        for outcome, hope, wards_preserved, branch_collapsed in cases:
            with self.subTest(outcome=outcome):
                state = self._state("part2_chain_troll")

                self.assertTrue(
                    self._episode(
                        label_choices("Turn the flood wheel", outcome)
                    ).run_scene(state)
                )

                self.assertEqual(state.character.hope, hope)
                self.assertEqual(
                    state.flags.get("part2_flood_wards_preserved", False),
                    wards_preserved,
                )
                self.assertEqual(
                    state.flags.get("part2_drowned_branch_collapsed", False),
                    branch_collapsed,
                )

    def test_chain_troll_defeat_continues_without_victory_claim(self) -> None:
        output: list[str] = []
        combat = RecordingCombat(CombatResult.DEFEAT)
        state = self._state("part2_chain_troll")
        state.character.hp = 0

        self.assertTrue(
            self._episode(
                label_choices("Turn the flood wheel", "Drain the Drowned Mile"),
                combat,
                output,
            ).run_scene(state)
        )

        self.assertEqual((state.character.hp, state.character.corruption), (1, 1))
        self.assertTrue(state.flags["part2_testimony_second"])
        self.assertNotIn("troll falls", "\n".join(output).lower())

    def test_each_combat_scene_builds_fresh_enemies_for_every_callback(self) -> None:
        combat = RecordingCombat()
        scenes = (
            ("part2_pursuit", label_choices("broken sword")),
            (
                "part2_echo_bridge",
                label_choices("exposed bridgehead", "Hunt the sapper"),
            ),
            (
                "part2_chain_troll",
                label_choices("Turn the flood wheel", "Drain the Drowned Mile"),
            ),
        )
        first_enemies = []
        for scene, choose in scenes:
            self.assertTrue(self._episode(choose, combat).run_scene(self._state(scene)))
            first_enemies.extend(combat.calls[-1]["enemies"])

        second = RecordingCombat()
        repeat_scenes = (
            ("part2_pursuit", label_choices("broken sword")),
            (
                "part2_echo_bridge",
                label_choices("exposed bridgehead", "Hunt the sapper"),
            ),
            (
                "part2_chain_troll",
                label_choices("Turn the flood wheel", "Drain the Drowned Mile"),
            ),
        )
        second_enemies = []
        for scene, choose in repeat_scenes:
            self.assertTrue(self._episode(choose, second).run_scene(self._state(scene)))
            second_enemies.extend(second.calls[-1]["enemies"])

        self.assertEqual(len(first_enemies), len(second_enemies))
        self.assertTrue(all(first is not other for first, other in zip(first_enemies, second_enemies)))

    def test_part_two_player_drives_high_hope_completionist_first_half(self) -> None:
        player = PartTwoPlayer()
        game = Game(
            TerminalUI(
                color=False,
                fast=True,
                input_fn=player.read,
                output_fn=player.write,
            )
        )
        game.state = self._state(
            "part2_descent",
            flags={
                "part_two_mara_present": True,
                "part_two_tobin_present": True,
            },
        )
        game.combat = VictoryCombat()

        for _ in range(4):
            self.assertTrue(game.part_two.run_scene(game.state))

        self.assertEqual(game.state.scene, "part2_echo_bridge")
        self.assertTrue(game.state.flags["part2_spoke_road_name"])
        self.assertTrue(game.state.flags["part2_testimony_first"])
        self.assertIn(QUEST_NAMES_LOST, game.state.quests)

        for _ in range(4):
            self.assertTrue(game.part_two.run_scene(game.state))

        self.assertEqual(game.state.scene, "part2_house_under_ash")
        self.assertFalse(game.combat.encounters[1]["config"].surprise_round)
        self.assertTrue(game.state.flags["part2_cipher_archive"])
        self.assertTrue(game.state.flags["part2_erased_statue"])
        self.assertTrue(game.state.flags["part2_testimony_first"])
        self.assertTrue(game.state.flags["part2_testimony_second"])
        self.assertTrue(game.state.flags["part2_prisoners_rescued"])
        self.assertGreaterEqual(game.state.character.hope, 4)
        self.assertLess(player.prompt_count, 300)

    def test_part_two_player_fails_loudly_after_300_prompts(self) -> None:
        player = PartTwoPlayer()
        player.prompt_count = 300

        with self.assertRaisesRegex(AssertionError, "300 prompts"):
            player.read("Enter your choice: ")

    def test_descent_collects_both_choices_then_advances_once(self) -> None:
        answers = iter((1, 1))
        headings: list[str] = []
        output: list[str] = []

        def choose(heading, _options):
            headings.append(heading)
            return next(answers)

        episode = PartTwoEpisode(
            TerminalUI(color=False, fast=True, output_fn=output.append),
            choose,
            lambda _state, _enemies, _config: None,
        )
        state = GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            scene="part2_descent",
            chapter=2,
            flags={"part_two_mara_present": True, "part_two_tobin_present": True},
            play_minutes=17,
        )

        self.assertTrue(episode.run_scene(state))

        self.assertEqual(headings, ["WHAT DO YOU CARRY DOWN?", "MARA HEARS THE RIDER ABOVE"])
        self.assertEqual((state.scene, state.play_minutes), ("part2_pursuit", 22))
        self.assertEqual((state.character.hope, state.character.corruption), (1, 0))
        self.assertEqual(state.character.mara_trust, 1)
        transcript = "\n".join(output)
        self.assertIn("Mara", transcript)
        self.assertIn("Tobin", transcript)

    def test_descent_menu_exit_at_either_prompt_leaves_state_unchanged(self) -> None:
        for answers in ((None,), (1, None)):
            with self.subTest(answers=answers):
                choices = iter(answers)
                output: list[str] = []
                episode = PartTwoEpisode(
                    TerminalUI(color=False, fast=True, output_fn=output.append),
                    lambda _heading, _options: next(choices),
                    lambda _state, _enemies, _config: None,
                )
                character = Character.from_origin("Arin", ORIGINS[0])
                character.hope = 3
                character.corruption = 2
                character.mara_trust = 4
                character.tobin_trust = 5
                state = GameState(
                    character,
                    scene="part2_descent",
                    chapter=2,
                    flags={
                        "part_two_mara_present": False,
                        "part_two_tobin_present": False,
                    },
                    play_minutes=11,
                )
                before = state.to_dict()

                self.assertFalse(episode.run_scene(state))

                self.assertEqual(state.to_dict(), before)
                transcript = "\n".join(output)
                self.assertNotIn("Mara", transcript)
                self.assertNotIn("Tobin", transcript)

class PartTwoLateEpisodeTests(PartTwoEpisodeTestCase):
    def test_house_collects_both_choices_before_mutating_and_departure_is_presence_aware(self) -> None:
        state = self._state(
            "part2_house_under_ash",
            flags={"part_two_mara_present": True},
        )
        state.character.mara_trust = -1
        before = state.to_dict()

        self.assertFalse(self._episode(label_choices("Keep moving", None)).run_scene(state))
        self.assertEqual(state.to_dict(), before)

        self.assertTrue(
            self._episode(label_choices("Keep moving", "child-height handprints")).run_scene(state)
        )
        self.assertTrue(state.flags["part2_mara_left"])
        self.assertFalse(state.flags["part_two_mara_present"])
        self.assertEqual((state.character.mara_trust, state.scene, state.play_minutes), (-2, "part2_burning_memory", 6))

        absent = self._state(
            "part2_house_under_ash",
            flags={"part_two_mara_present": False},
        )
        absent.character.mara_trust = 7
        self.assertTrue(
            self._episode(label_choices("Keep moving", "service passage")).run_scene(absent)
        )
        self.assertEqual(absent.character.mara_trust, 7)
        self.assertEqual((absent.scene, absent.play_minutes), ("part2_burning_memory", 6))

    def test_sharing_forge_truth_or_rescuing_prisoners_keeps_mara_present(self) -> None:
        cases = (
            ({"part_two_mara_present": True}, "Share the forge truth", -1, True),
            (
                {"part_two_mara_present": True, "part2_prisoners_rescued": True},
                "Keep moving",
                -3,
                False,
            ),
        )
        for flags, truth_choice, expected_trust, shared_truth in cases:
            with self.subTest(truth_choice=truth_choice):
                output: list[str] = []
                state = self._state("part2_house_under_ash", flags=flags)
                state.character.mara_trust = -2

                self.assertTrue(
                    self._episode(
                        label_choices(truth_choice, "ruined dormitory"), output=output
                    ).run_scene(state)
                )

                self.assertEqual(state.character.mara_trust, expected_trust)
                self.assertEqual(
                    state.flags.get("part2_shared_mara_truth", False), shared_truth
                )
                self.assertTrue(state.flags["part_two_mara_present"])
                self.assertFalse(state.flags.get("part2_mara_left", False))
                if truth_choice.startswith("Share"):
                    self.assertIn("does not get to make my silence", " ".join(output))

    def test_fixed_party_compositions_require_mara_and_tobin_without_hiding_scene_art(self) -> None:
        cases = (
            (
                "part2_descent",
                ("Calenor's lesson", "Trust"),
                (part_two_art.FALLING_SILVER_STAIR_ART, part_two_art.COMPANIONS_DESCENDING_ART),
                (
                    part_two_art.PART_TWO_TITLE_ART,
                    part_two_art.RIDER_WAYHOUSE_THRESHOLD_ART,
                    part_two_art.CALENOR_BROKEN_SWORD_ART,
                ),
            ),
            (
                "part2_echo_bridge",
                ("exposed bridgehead", "Defend the ropes"),
                (part_two_art.ECHO_BRIDGE_BATTLE_ART,),
                (part_two_art.ECHO_BRIDGE_ART, part_two_art.ORC_SAPPER_INTRO_ART),
            ),
            (
                "part2_chain_troll",
                ("Turn the flood wheel", "Drain the Drowned Mile"),
                (part_two_art.CHAIN_TROLL_BATTLE_ART,),
                (
                    part_two_art.CHAIN_TROLL_INTRO_ART,
                    part_two_art.SECOND_WARDEN_TESTIMONY_ART,
                ),
            ),
            (
                "part2_last_seal",
                ("Divide", "Reject", "Leave together"),
                (part_two_art.EIGHT_SPOKED_RITUAL_ART,),
                (part_two_art.LAST_SEAL_VAULT_ART,),
            ),
            (
                "part2_final_battle",
                ("Hold the center",),
                (part_two_art.FINAL_SEAL_BATTLE_ART,),
                (part_two_art.RIDER_FINAL_ENTRANCE_ART,),
            ),
        )
        missing_companion_flags = (
            {"part_two_mara_present": False, "part_two_tobin_present": True},
            {"part_two_mara_present": True, "part_two_tobin_present": False},
        )
        for scene, choices, guarded_art, adjacent_art in cases:
            for flags in missing_companion_flags:
                with self.subTest(scene=scene, flags=flags):
                    ui = ArtRecordingUI(color=False, fast=True, output_fn=lambda _line: None)
                    episode = PartTwoEpisode(ui, label_choices(*choices), RecordingCombat())
                    state = self._state(scene, flags=flags)

                    self.assertTrue(episode.run_scene(state))

                    observed_ids = {id(art) for art, _color, _alt in ui.art_calls}
                    for composition in guarded_art:
                        self.assertNotIn(id(composition), observed_ids)
                    for composition in adjacent_art:
                        self.assertIn(id(composition), observed_ids)

    def test_mara_forge_art_requires_only_mara_and_keeps_drowned_location_art(self) -> None:
        cases = (
            (False, True, False),
            (True, False, True),
        )
        for mara_present, tobin_present, forge_expected in cases:
            with self.subTest(mara=mara_present, tobin=tobin_present):
                ui = ArtRecordingUI(color=False, fast=True, output_fn=lambda _line: None)
                episode = PartTwoEpisode(
                    ui,
                    label_choices("prisoners"),
                    RecordingCombat(),
                )
                state = self._state(
                    "part2_drowned_mile",
                    flags={
                        "part_two_mara_present": mara_present,
                        "part_two_tobin_present": tobin_present,
                    },
                )

                self.assertTrue(episode.run_scene(state))

                observed_ids = {id(art) for art, _color, _alt in ui.art_calls}
                self.assertIn(id(part_two_art.DROWNED_MILE_ART), observed_ids)
                self.assertIn(id(part_two_art.DROWNED_CARAVAN_ART), observed_ids)
                self.assertEqual(
                    id(part_two_art.MARA_SHACKLE_FORGE_ART) in observed_ids,
                    forge_expected,
                )

    def test_teren_duel_art_appears_only_when_combat_really_occurs(self) -> None:
        cases = (
            (
                {"part2_cipher_archive": True, "part2_erased_statue": True},
                False,
            ),
            ({"part2_cipher_archive": True}, True),
        )
        for flags, duel_expected in cases:
            with self.subTest(duel=duel_expected):
                ui = ArtRecordingUI(color=False, fast=True, output_fn=lambda _line: None)
                combat = RecordingCombat()
                episode = PartTwoEpisode(
                    ui,
                    label_choices("Present the evidence", "Spare Teren"),
                    combat,
                )
                state = self._state("part2_teren", flags=flags)

                self.assertTrue(episode.run_scene(state))

                observed_ids = [id(art) for art, _color, _alt in ui.art_calls]
                self.assertEqual(observed_ids[0], id(part_two_art.TEREN_REVEAL_ART))
                self.assertEqual(
                    id(part_two_art.FALSE_RANGER_DUEL_ART) in observed_ids,
                    duel_expected,
                )
                self.assertEqual(len(combat.calls), int(duel_expected))
                if duel_expected:
                    self.assertEqual(
                        observed_ids[:2],
                        [id(part_two_art.TEREN_REVEAL_ART), id(part_two_art.FALSE_RANGER_DUEL_ART)],
                    )

    def test_party_endings_are_guarded_but_resolved_shadow_ending_and_map_remain(self) -> None:
        guarded_endings = (
            ("Remake the seal", part_two_art.LIVING_ROAD_ENDING_ART),
            ("Renew the ancient seal", part_two_art.LAST_WARDEN_ENDING_ART),
            ("Destroy the Dead Road", part_two_art.ROAD_IN_RUIN_ENDING_ART),
        )
        missing_companion_flags = (
            {"part_two_mara_present": False, "part_two_tobin_present": True},
            {"part_two_mara_present": True, "part_two_tobin_present": False},
        )
        for choice, guarded_art in guarded_endings:
            for flags in missing_companion_flags:
                with self.subTest(choice=choice, flags=flags):
                    ui = ArtRecordingUI(color=False, fast=True, output_fn=lambda _line: None)
                    state = self._remake_state()
                    state.flags.update(flags)
                    state.character.mara_trust = 2
                    state.character.tobin_trust = 2

                    self.assertTrue(
                        PartTwoEpisode(ui, label_choices(choice), RecordingCombat()).run_scene(state)
                    )

                    observed_ids = {id(art) for art, _color, _alt in ui.art_calls}
                    self.assertNotIn(id(guarded_art), observed_ids)
                    self.assertIn(id(part_two_art.FORNOST_MAP_CLIFFHANGER_ART), observed_ids)

        ui = ArtRecordingUI(color=False, fast=True, output_fn=lambda _line: None)
        override = self._state(
            "part2_seal_choice",
            flags={"part_two_mara_present": False, "part_two_tobin_present": False},
            quests=[QUEST_DEAD_ROAD_FATE],
        )
        override.character.corruption = 4

        self.assertTrue(
            PartTwoEpisode(
                ui,
                label_choices("Destroy the Dead Road"),
                RecordingCombat(),
            ).run_scene(override)
        )

        observed_ids = [id(art) for art, _color, _alt in ui.art_calls]
        self.assertEqual(override.ending, "shadows_name")
        self.assertEqual(
            observed_ids,
            [
                id(part_two_art.SHADOWS_NAME_ENDING_ART),
                id(part_two_art.FORNOST_MAP_CLIFFHANGER_ART),
            ],
        )

    def test_part_two_animations_emit_one_screen_reader_alt_or_one_final_lit_frame(self) -> None:
        animations = (
            (
                part_two_art.WALL_NAMES_AWAKENING_ART,
                part_two_art.WALL_NAMES_LIT_FRAME,
                "Eight columns of names awaken across a dark stone wall.",
            ),
            (
                part_two_art.FORNOST_MAP_CLIFFHANGER_ART,
                part_two_art.FORNOST_MAP_LIT_FRAME,
                "A branching underground map points to a sealed node beneath ruined Fornost.",
            ),
        )
        for animation, final_frame, alt_text in animations:
            with self.subTest(alt=alt_text):
                screen_reader_output: list[str] = []
                screen_reader_sleeps: list[float] = []
                TerminalUI(
                    color=False,
                    fast=False,
                    screen_reader=True,
                    output_fn=screen_reader_output.append,
                    sleep_fn=screen_reader_sleeps.append,
                ).art(animation, Color.YELLOW, alt_text=alt_text)
                self.assertEqual(screen_reader_output, [f"[Scene: {alt_text}]"])
                self.assertEqual(screen_reader_sleeps, [])

                reduced_output: list[str] = []
                reduced_sleeps: list[float] = []
                TerminalUI(
                    color=False,
                    fast=False,
                    reduced_motion=True,
                    output_fn=reduced_output.append,
                    sleep_fn=reduced_sleeps.append,
                ).art(animation, Color.YELLOW, alt_text=alt_text)
                expected_output: list[str] = []
                TerminalUI(
                    color=False,
                    fast=True,
                    output_fn=expected_output.append,
                ).art(final_frame, Color.YELLOW, alt_text=alt_text)
                self.assertEqual(reduced_output, expected_output)
                self.assertEqual(reduced_sleeps, [])

    def test_burning_memory_is_atomic_and_memory_is_not_strong_teren_evidence(self) -> None:
        state = self._state("part2_burning_memory", play_minutes=51)
        before = state.to_dict()
        self.assertFalse(
            self._episode(label_choices("Search every room", "Lift the board", None)).run_scene(state)
        )
        self.assertEqual(state.to_dict(), before)

        self.assertTrue(
            self._episode(
                label_choices("Search every room", "Lift the board", "Take his hand")
            ).run_scene(state)
        )
        self.assertTrue(state.flags["part2_memory_complete"])
        self.assertEqual((state.scene, state.play_minutes), ("part2_teren", 63))

        combat = RecordingCombat()
        state.flags["part2_cipher_archive"] = True
        self.assertTrue(
            self._episode(label_choices("Present the evidence", "Spare Teren"), combat).run_scene(state)
        )
        self.assertEqual(len(combat.calls), 1)
        self.assertFalse(state.flags.get("part2_teren_confessed", False))

    def test_teren_token_plus_one_strong_piece_avoids_duel(self) -> None:
        combat = RecordingCombat()
        state = self._state(
            "part2_teren",
            flags={"part2_erased_statue": True, "part_two_mara_present": True},
        )
        state.character.add_item("ranger_token")

        self.assertTrue(
            self._episode(label_choices("Invoke Calenor's Ranger token", "Bind Teren"), combat).run_scene(state)
        )

        self.assertEqual(combat.calls, [])
        self.assertTrue(state.flags["part2_teren_confessed"])
        self.assertTrue(state.flags["part2_teren_bound"])
        self.assertEqual((state.scene, state.play_minutes), ("part2_calenor_prison", 10))

    def test_teren_attack_and_duel_defeat_continue_to_a_plausible_fate(self) -> None:
        output: list[str] = []
        combat = RecordingCombat(CombatResult.DEFEAT)
        state = self._state("part2_teren", flags={"part_two_mara_present": False})
        state.character.hp = 0
        state.character.mara_trust = 5

        self.assertTrue(
            self._episode(label_choices("Attack before", "Kill Teren"), combat, output).run_scene(state)
        )

        enemy = combat.calls[0]["enemies"][0]
        self.assertEqual((enemy.name, enemy.archetype), ("Teren the False Ranger", "duelist"))
        self.assertTrue(combat.calls[0]["config"].surprise_round)
        self.assertTrue(state.flags["part2_teren_killed"])
        self.assertEqual((state.character.hp, state.character.corruption), (1, 3))
        self.assertEqual(state.character.mara_trust, 5)
        self.assertIn("falling masonry", "\n".join(output))

    def test_calenor_prison_oath_requires_two_testimonies_and_all_answers_are_atomic(self) -> None:
        captured: list[tuple[str, ...]] = []
        state = self._state(
            "part2_calenor_prison",
            flags={"part2_testimony_first": True},
            quests=[QUEST_REACH_CALENOR],
        )
        state.character.add_item("calenor_broken_sword")

        def exit_after_capture(_heading, options):
            captured.append(tuple(options))
            return None

        self.assertFalse(self._episode(exit_after_capture).run_scene(state))
        self.assertFalse(any("Warden oath" in option for option in captured[0]))

        state.flags["part2_testimony_second"] = True
        before = state.to_dict()
        self.assertFalse(self._episode(label_choices("Warden oath", None)).run_scene(state))
        self.assertEqual(state.to_dict(), before)

        self.assertTrue(
            self._episode(label_choices("Warden oath", "Bring him home")).run_scene(state)
        )
        self.assertIn("calenor_broken_sword", state.character.inventory)
        self.assertIn(QUEST_REACH_CALENOR, state.completed_quests)
        self.assertEqual((state.scene, state.play_minutes), ("part2_calenor_reunion", 8))

    def test_reunion_requires_all_truths_and_completes_the_third_testimony_once(self) -> None:
        flags = {"part2_testimony_first": True, "part2_testimony_second": True}
        state = self._state(
            "part2_calenor_reunion",
            flags=flags,
            quests=[QUEST_LAST_SEAL, QUEST_NAMES_LOST],
        )
        before = state.to_dict()
        self.assertFalse(
            self._episode(
                label_choices("Why hide", "What did Teren", None)
            ).run_scene(state)
        )
        self.assertEqual(state.to_dict(), before)

        output: list[str] = []
        self.assertTrue(
            self._episode(
                label_choices(
                    "Why hide",
                    "What did Teren",
                    "Why must the Rider",
                    "Forgive Calenor",
                ),
                output=output,
            ).run_scene(state)
        )

        self.assertTrue(state.flags["part2_testimony_third"])
        self.assertEqual(state.character.hope, 1)
        self.assertIn(QUEST_NAMES_LOST, state.completed_quests)
        self.assertIn(QUEST_LAST_SEAL, state.completed_quests)
        self.assertIn(QUEST_EIGHTH_NAME, state.quests)
        self.assertEqual((state.scene, state.play_minutes), ("part2_vigil", 10))
        transcript = "\n".join(output)
        self.assertIn("love was the one lock", transcript)
        self.assertNotIn("birth-name is", transcript)

    def test_last_seal_collects_both_answers_before_applying_effects(self) -> None:
        state = self._state("part2_last_seal", quests=[QUEST_EIGHTH_NAME])
        before = state.to_dict()
        self.assertFalse(
            self._episode(label_choices("Divide", None)).run_scene(state)
        )
        self.assertEqual(state.to_dict(), before)

        self.assertTrue(
            self._episode(label_choices("Divide", "Reject")).run_scene(state)
        )
        self.assertTrue(state.flags["part2_star_rejected"])
        self.assertEqual(state.character.hope, 1)
        self.assertIn(QUEST_DEAD_ROAD_FATE, state.quests)
        self.assertEqual((state.scene, state.play_minutes), ("part2_final_battle", 6))

    def test_final_rider_uses_six_invulnerable_rounds_and_stacked_fresh_reductions(self) -> None:
        combat = RecordingCombat()
        state = self._state(
            "part2_final_battle",
            flags={
                "part2_calenor_commanded": True,
                "part2_drowned_mile_preserved": True,
                "part2_drowned_branch_collapsed": True,
                "part_two_mara_present": True,
                "part_two_tobin_present": False,
            },
        )

        self.assertTrue(
            self._episode(label_choices("Challenge the Rider"), combat).run_scene(state)
        )

        rider = combat.calls[0]["enemies"][0]
        config = combat.calls[0]["config"]
        self.assertEqual((rider.name, rider.hp, rider.attack_min, rider.attack_max), ("Black Rider", 999, 2, 5))
        self.assertEqual(config.max_rounds, 6)
        self.assertFalse(config.surprise_round)
        self.assertTrue(config.objective_enemy_invulnerable)
        self.assertEqual(config.objective, "Survive six rounds while the Last Seal is remade")
        self.assertTrue(config.mara_aid)
        self.assertFalse(config.tobin_aid)
        self.assertEqual((state.character.corruption, state.scene, state.play_minutes), (1, "part2_seal_choice", 8))

    def test_final_defeat_applies_exactly_one_cost_in_priority_order(self) -> None:
        cases = (
            (
                {"part2_sword_broke_chain": True, "part2_teren_spared": True, "part2_final_ritual_guarded": True},
                "broken sword takes the empty spoke",
                None,
                True,
                "Hold the center",
            ),
            ({"part2_teren_spared": True}, "Teren takes the empty spoke", "part2_teren_took_spoke", False, "Hold the center"),
            ({}, "leaves a silver scar", None, False, "Guard the ritual"),
            ({}, "Calenor is drawn back", "part2_calenor_rebound", False, "Hold the center"),
        )
        cost_flags = {
            "part2_teren_took_spoke",
            "part2_calenor_rebound",
        }
        for flags, expected_text, expected_flag, add_sword, tactic in cases:
            with self.subTest(expected_text=expected_text):
                state = self._state("part2_final_battle", flags=flags)
                output: list[str] = []
                if add_sword:
                    state.character.add_item("calenor_broken_sword")

                self.assertTrue(
                    self._episode(
                        label_choices(tactic),
                        RecordingCombat(CombatResult.DEFEAT),
                        output,
                    ).run_scene(state)
                )

                self.assertEqual(state.character.hp, 1)
                self.assertEqual(
                    {flag for flag in cost_flags if state.flags.get(flag, False)},
                    {expected_flag} if expected_flag else set(),
                )
                self.assertIn(expected_text, " ".join(output))
                if add_sword:
                    self.assertNotIn("calenor_broken_sword", state.character.inventory)

    def test_ending_resolver_and_dynamic_remake_use_semantic_choices(self) -> None:
        state = self._remake_state()
        self.assertEqual(part_two_ending(state, "remake"), "living_road")
        self.assertEqual(part_two_ending(state, "destroy"), "road_in_ruin")
        self.assertEqual(part_two_ending(state, "renew"), "last_warden")
        self.assertEqual(part_two_ending(state, "claim"), "shadows_name")
        state.character.hope = 0
        state.character.corruption = 4
        self.assertEqual(part_two_ending(state, "remake"), "shadows_name")

        state = self._remake_state()
        seen: list[tuple[str, ...]] = []

        def choose(_heading, options):
            seen.append(tuple(options))
            return next(index for index, option in enumerate(options, 1) if "Destroy" in option)

        self.assertTrue(self._episode(choose).run_scene(state))
        self.assertTrue(any("Remake" in option for option in seen[0]))
        self.assertEqual(state.ending, "road_in_ruin")
        self.assertTrue(state.flags["part2_seal_choice_destroy"])

    def test_ineligible_remake_is_absent_and_ending_cleans_quests_truthfully_once(self) -> None:
        state = self._state(
            "part2_seal_choice",
            quests=[
                QUEST_EIGHTH_NAME,
                QUEST_DEAD_ROAD_FATE,
                QUEST_NAMES_LOST,
                QUEST_PRISONERS_ASH,
            ],
        )
        seen: list[tuple[str, ...]] = []

        def choose(_heading, options):
            seen.append(tuple(options))
            return next(index for index, option in enumerate(options, 1) if "Claim" in option)

        self.assertTrue(self._episode(choose).run_scene(state))

        self.assertFalse(any("Remake" in option for option in seen[0]))
        self.assertEqual((state.chapter, state.scene, state.ending), (2, "complete", "shadows_name"))
        self.assertIn(QUEST_DEAD_ROAD_FATE, state.completed_quests)
        self.assertNotIn(QUEST_EIGHTH_NAME, state.completed_quests)
        self.assertNotIn(QUEST_NAMES_LOST, state.completed_quests)
        self.assertNotIn(QUEST_PRISONERS_ASH, state.completed_quests)
        self.assertEqual(state.quests, [])
        self.assertEqual(
            state.journal.count("An underground map revealed another sealed spoke beneath ruined Fornost."),
            1,
        )
        self.assertEqual(state.play_minutes, 5)

    def test_shadow_override_records_the_attempted_seal_choice_without_false_success(self) -> None:
        state = self._state("part2_seal_choice", quests=[QUEST_DEAD_ROAD_FATE])
        state.character.corruption = 4

        self.assertTrue(self._episode(label_choices("Destroy the Dead Road")).run_scene(state))

        self.assertEqual(state.ending, "shadows_name")
        self.assertTrue(state.flags.get("part2_seal_choice_destroy", False))
        self.assertFalse(state.flags.get("part2_seal_destroyed", False))

    def test_final_rebound_blocks_living_road_and_remains_the_single_consequence(self) -> None:
        state = self._remake_state()
        state.scene = "part2_final_battle"
        state.flags.update(
            {
                "part2_teren_bound": True,
            }
        )
        defeat = RecordingCombat(CombatResult.DEFEAT)

        self.assertTrue(
            self._episode(label_choices("Hold the center"), defeat).run_scene(state)
        )
        self.assertTrue(state.flags["part2_calenor_rebound"])

        seen: list[tuple[str, ...]] = []

        def renew_without_remake(_heading, options):
            seen.append(tuple(options))
            return next(index for index, option in enumerate(options, 1) if "Renew" in option)

        self.assertTrue(self._episode(renew_without_remake).run_scene(state))

        self.assertFalse(any("Remake" in option for option in seen[0]))
        self.assertEqual(state.ending, "last_warden")
        self.assertTrue(state.flags["part2_calenor_rebound"])
        self.assertFalse(state.flags.get("part2_calenor_escaped", False))
        self.assertFalse(state.flags.get("part2_calenor_remained", False))

    def test_final_rebound_survives_every_offered_seal_fate_and_destroy_uses_company(self) -> None:
        cases = (
            ("Renew the ancient seal", "last_warden"),
            ("Destroy the Dead Road", "road_in_ruin"),
            ("Claim the road", "shadows_name"),
        )
        for target, expected_ending in cases:
            with self.subTest(target=target):
                state = self._remake_state()
                state.scene = "part2_final_battle"
                state.flags.update(
                    {
                        "part2_teren_bound": True,
                        "part2_ritual_collapse_prepared": True,
                    }
                )

                self.assertTrue(
                    self._episode(
                        label_choices("Hold the center"),
                        RecordingCombat(CombatResult.DEFEAT),
                    ).run_scene(state)
                )
                self.assertTrue(state.flags["part2_calenor_rebound"])

                seen: list[tuple[str, ...]] = []
                output: list[str] = []

                def choose(_heading, options):
                    seen.append(tuple(options))
                    return next(
                        index for index, option in enumerate(options, 1) if target in option
                    )

                self.assertTrue(self._episode(choose, output=output).run_scene(state))

                self.assertFalse(any("Remake" in option for option in seen[0]))
                self.assertEqual(state.ending, expected_ending)
                self.assertTrue(state.flags["part2_calenor_rebound"])
                self.assertFalse(state.flags.get("part2_calenor_collapsed_road", False))
                self.assertFalse(state.flags.get("part2_calenor_escaped", False))
                self.assertFalse(state.flags.get("part2_calenor_remained", False))
                guardians = dict(part_two_ending_breakdown(state))["Calenor and Teren"]
                self.assertIn("rebound Calenor", guardians)

                if expected_ending == "road_in_ruin":
                    self.assertTrue(state.flags.get("part2_company_collapsed_road", False))
                    transcript = "\n".join(output).lower()
                    self.assertIn("company", transcript)
                    self.assertIn("prepared", transcript)
                    self.assertNotIn("calenor triggers", transcript)
                else:
                    self.assertFalse(state.flags.get("part2_company_collapsed_road", False))

    def test_teren_spoke_cost_survives_every_offered_seal_fate(self) -> None:
        cases = (
            ("Renew the ancient seal", "last_warden"),
            ("Remake the seal", "living_road"),
            ("Destroy the Dead Road", "road_in_ruin"),
            ("Claim the road", "shadows_name"),
        )
        for target, expected_ending in cases:
            with self.subTest(target=target):
                state = self._remake_state()
                state.scene = "part2_final_battle"
                state.flags.update(
                    {
                        "part2_teren_spared": True,
                        "part2_ritual_collapse_prepared": True,
                    }
                )

                self.assertTrue(
                    self._episode(
                        label_choices("Hold the center"),
                        RecordingCombat(CombatResult.DEFEAT),
                    ).run_scene(state)
                )
                self.assertTrue(state.flags["part2_teren_took_spoke"])

                seen: list[tuple[str, ...]] = []
                output: list[str] = []

                def choose(_heading, options):
                    seen.append(tuple(options))
                    return next(
                        index for index, option in enumerate(options, 1) if target in option
                    )

                self.assertTrue(self._episode(choose, output=output).run_scene(state))

                for offered in ("Renew", "Remake", "Destroy", "Claim"):
                    self.assertTrue(any(offered in option for option in seen[0]))
                self.assertEqual(state.ending, expected_ending)
                self.assertTrue(state.flags["part2_teren_took_spoke"])
                self.assertFalse(state.flags.get("part2_teren_stayed_to_collapse", False))
                guardians = dict(part_two_ending_breakdown(state))["Calenor and Teren"]
                self.assertIn("Teren took the empty spoke", guardians)
                self.assertNotIn("Teren stayed", guardians)

                transcript = "\n".join(output).lower()
                self.assertNotIn("teren stays to break", transcript)
                if expected_ending == "road_in_ruin":
                    self.assertTrue(state.flags.get("part2_company_collapsed_road", False))
                    self.assertIn("company", transcript)
                    self.assertIn("prepared", transcript)
                else:
                    self.assertFalse(state.flags.get("part2_company_collapsed_road", False))

    def test_draining_after_preserving_wards_clears_the_stale_finale_reduction(self) -> None:
        combat = RecordingCombat()
        state = self._state(
            "part2_chain_troll",
            flags={"part2_flood_wards_preserved": True},
        )

        self.assertTrue(
            self._episode(
                label_choices("Turn the flood wheel", "Drain the Drowned Mile"), combat
            ).run_scene(state)
        )

        self.assertFalse(state.flags.get("part2_flood_wards_preserved", False))
        self.assertFalse(state.flags.get("part2_drowned_mile_preserved", False))
        self.assertFalse(state.flags.get("part2_drowned_branch_collapsed", False))
        self.assertEqual(state.character.hope, 1)

        state.scene = "part2_final_battle"
        self.assertTrue(
            self._episode(label_choices("Hold the center"), combat).run_scene(state)
        )
        rider = combat.calls[-1]["enemies"][0]
        self.assertEqual((rider.attack_min, rider.attack_max), (6, 9))

    def test_shadow_breakdown_describes_corruption_override_not_a_false_claim_choice(self) -> None:
        state = self._state("part2_seal_choice", quests=[QUEST_DEAD_ROAD_FATE])
        state.character.corruption = 4
        self.assertTrue(self._episode(label_choices("Destroy the Dead Road")).run_scene(state))

        road = dict(part_two_ending_breakdown(state))["The Dead Road"]

        self.assertIn("attempt to destroy", road.lower())
        self.assertNotIn("claimed road", road.lower())

    def test_bound_teren_breakdown_states_his_actual_fate_without_false_payoff(self) -> None:
        state = self._state(
            "complete",
            flags={"part2_teren_bound": True},
        )
        state.ending = "last_warden"

        guardians = dict(part_two_ending_breakdown(state))["Calenor and Teren"]

        self.assertIn("bound for judgment", guardians)
        self.assertNotIn("shapes its cost", guardians)

    def test_part_two_breakdown_has_five_chapter_specific_labels(self) -> None:
        state = self._remake_state()
        state.ending = "living_road"
        state.flags["part2_teren_spared"] = True
        self.assertEqual(
            [label for label, _text in part_two_ending_breakdown(state)],
            ["The Eighth Name", "Mara", "Tobin and Ned", "Calenor and Teren", "The Dead Road"],
        )

    @classmethod
    def _remake_state(cls) -> GameState:
        state = cls._state(
            "part2_seal_choice",
            flags={
                "part2_testimony_first": True,
                "part2_testimony_second": True,
                "part2_testimony_third": True,
                "part2_prisoners_rescued": True,
                "part_two_mara_present": True,
            },
            quests=[QUEST_EIGHTH_NAME, QUEST_DEAD_ROAD_FATE],
        )
        state.character.hope = 3
        state.character.corruption = 1
        state.character.mara_trust = 2
        return state


if __name__ == "__main__":
    unittest.main()
