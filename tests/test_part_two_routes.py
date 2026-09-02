import random
import unittest

from roads_beneath_shadow.app import Game
from roads_beneath_shadow.combat import (
    CombatDifficulty,
    CombatEngine,
    CombatResult,
)
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.part_two import PartTwoEpisode
from roads_beneath_shadow.ui import TerminalUI
from tests.helpers import EpisodePlayer, PartTwoPlayer, VictoryCombat


class LowEvidencePartTwoPlayer(PartTwoPlayer):
    """Takes the five-combat route while keeping the rest of Part II coherent."""

    def _answer(self, prompt: str, context: str) -> str:
        fixed = {
            "THE HALL ASKS FOR A NAME": "Refuse to speak",
            "HOW DO YOU BREAK THE SPOKE-CHAIN?": "broken sword",
            "WHAT BECOMES OF THE LAST SEAL?": "Renew the ancient seal",
        }
        for heading, label in fixed.items():
            if heading in context:
                return self._visible_choice(context, label)
        if "EXPLORE THE HALL OF EIGHT" in context:
            for label in ("Cipher Archive", "Dead Testimony", "Take the road to Echo Bridge"):
                if label in context:
                    return self._visible_choice(context, label)
        return super()._answer(prompt, context)


class DefendOnlyPlayer(EpisodePlayer):
    def _answer(self, prompt: str, context: str) -> str:
        if "Choose your action" in context:
            return "1"
        return super()._answer(prompt, context)


class PartTwoRouteTests(unittest.TestCase):
    def test_real_handoff_completionist_route_meets_the_episode_contract(self) -> None:
        player = PartTwoPlayer()
        game, combat = self._fellowship_game(player, play_minutes=60)

        game._begin_part_two()
        starting_minutes = game.state.play_minutes
        story_prompts = 0
        story_choice = game.part_two.story_choice

        def counted_story_choice(heading, options):
            nonlocal story_prompts
            story_prompts += 1
            return story_choice(heading, options)

        game.part_two.story_choice = counted_story_choice
        game._run_journey()

        state = game.state
        transcript = "\n".join(player.output)
        part_two_minutes = state.play_minutes - starting_minutes
        self.assertEqual((state.chapter, state.scene, state.ending), (2, "complete", "living_road"))
        self.assertGreaterEqual(part_two_minutes, 120)
        self.assertLessEqual(part_two_minutes, 140)
        self.assertEqual(part_two_minutes, 132)
        self.assertGreaterEqual(story_prompts, 33)
        self.assertEqual(len(combat.encounters), 4)
        self.assertTrue(state.flags["part2_prisoners_rescued"])
        self.assertTrue(
            all(
                state.flags[flag]
                for flag in (
                    "part2_testimony_first",
                    "part2_testimony_second",
                    "part2_testimony_third",
                )
            )
        )
        self.assertFalse(state.flags["part_two_hidden_route_known"])
        self.assertEqual(state.quests, [])
        self.assertNotIn("Unknown scene", transcript)
        self.assertNotIn("AttributeError", transcript)

    def test_real_handoff_low_evidence_route_forces_the_fifth_combat(self) -> None:
        player = LowEvidencePartTwoPlayer()
        game, combat = self._fellowship_game(player, play_minutes=60)

        game._begin_part_two()
        starting_minutes = game.state.play_minutes
        game._run_journey()

        state = game.state
        transcript = "\n".join(player.output)
        self.assertEqual((state.chapter, state.scene, state.ending), (2, "complete", "last_warden"))
        self.assertEqual(state.play_minutes - starting_minutes, 128)
        self.assertEqual(len(combat.encounters), 5)
        teren_encounters = [
            encounter
            for encounter in combat.encounters
            if "Teren the False Ranger" in encounter["enemies"]
        ]
        self.assertEqual(len(teren_encounters), 1)
        self.assertFalse(teren_encounters[0]["config"].surprise_round)
        self.assertTrue(state.flags["part2_cipher_archive"])
        self.assertFalse(state.flags.get("part2_erased_statue", False))
        self.assertFalse(state.flags.get("part2_testimony_first", False))
        self.assertTrue(state.flags["part2_sword_broke_chain"])
        self.assertIn("testimony remains unanswered", transcript)
        self.assertNotIn("Speak the Warden oath carried by two testimonies", transcript)
        self.assertNotIn("Remake the seal as a freely shared oath", transcript)

    def test_real_story_combat_pursuit_preserves_the_invulnerable_rider(self) -> None:
        state, rider, config, result, transcript = self._run_real_rider_scene(
            "part2_pursuit", seed=17
        )

        self.assertEqual(result, CombatResult.VICTORY)
        self.assertTrue(state.character.alive)
        self.assertEqual((rider.hp, rider.max_hp), (999, 999))
        self.assertEqual(rider.statuses, {})
        self.assertTrue(config.objective_enemy_invulnerable)
        self.assertFalse(config.surprise_round)
        self.assertEqual(config.max_rounds, 4)
        self._assert_no_rider_damage_claim(transcript)

    def test_real_story_combat_finale_preserves_the_invulnerable_rider(self) -> None:
        state, rider, config, result, transcript = self._run_real_rider_scene(
            "part2_final_battle", seed=23
        )

        self.assertEqual(result, CombatResult.VICTORY)
        self.assertTrue(state.character.alive)
        self.assertEqual((rider.hp, rider.max_hp), (999, 999))
        self.assertEqual(rider.statuses, {})
        self.assertTrue(config.objective_enemy_invulnerable)
        self.assertFalse(config.surprise_round)
        self.assertEqual(config.max_rounds, 6)
        self._assert_no_rider_damage_claim(transcript)

    def test_screen_reader_route_from_real_handoff_keeps_the_ending_understandable(self) -> None:
        player = PartTwoPlayer()
        game, _combat = self._fellowship_game(player, screen_reader=True)

        game._begin_part_two()
        game._run_journey()

        transcript = "\n".join(player.output)
        self.assertEqual((game.state.scene, game.state.ending), ("complete", "living_road"))
        self.assertIn("the Eighth Name is its Warden oath-title", transcript)
        self.assertIn("another sealed spoke beneath ruined Fornost", transcript)
        self.assertIn("We guarded the road. The Shadow was waking the city.", transcript)
        self.assertNotIn("\x1b", transcript)


    def test_part_two_ending_screen_uses_fornost_coda_without_part_two_launch_option(self) -> None:
        output: list[str] = []
        ui = TerminalUI(
            color=False,
            fast=True,
            input_fn=lambda _prompt: "2",
            output_fn=output.append,
        )
        game = Game(ui)
        game.state = GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            chapter=2,
            scene="complete",
            ending="living_road",
            flags={
                "part2_testimony_first": True,
                "part2_testimony_second": True,
                "part2_testimony_third": True,
                "part_two_mara_present": True,
            },
        )

        game._show_ending()

        transcript = "\n".join(output)
        self.assertIn("PART II COMPLETE", transcript)
        self.assertIn("The Eighth Name:", transcript)
        self.assertIn("These choices shape the road to Fornost.", transcript)
        self.assertIn("We guarded the road. The Shadow was waking the city.", transcript)
        self.assertIn("The road continues in Part III: The Waking City.", transcript)
        self.assertNotIn("Begin Part II", transcript)
        self.assertNotIn("PART I COMPLETE", transcript)


    def _run_real_rider_scene(self, scene: str, *, seed: int):
        player = DefendOnlyPlayer()
        ui = TerminalUI(
            color=False,
            fast=True,
            input_fn=player.read,
            output_fn=player.write,
        )
        engine = CombatEngine(ui, random.Random(seed), difficulty=CombatDifficulty.STORY)
        captured: dict[str, object] = {}

        def combat(state, enemies, config):
            captured["rider"] = enemies[0]
            captured["config"] = config
            captured["result"] = engine.run(state, enemies, config)
            return captured["result"]

        state = GameState(
            Character.from_origin("Arin", ORIGINS[0]),
            chapter=2,
            scene=scene,
        )
        episode = PartTwoEpisode(ui, lambda _heading, _options: 1, combat)

        self.assertTrue(episode.run_scene(state))

        return (
            state,
            captured["rider"],
            captured["config"],
            captured["result"],
            "\n".join(player.output),
        )

    @staticmethod
    def _fellowship_game(
        player: PartTwoPlayer,
        *,
        screen_reader=False,
        play_minutes=0,
        ui=None,
    ):
        game = Game(
            ui
            or TerminalUI(
                color=False,
                fast=True,
                screen_reader=screen_reader,
                input_fn=player.read,
                output_fn=player.write,
            )
        )
        combat = VictoryCombat()
        game.combat = combat
        character = Character.from_origin("Arin", ORIGINS[0])
        character.hope = 3
        character.mara_trust = 3
        character.tobin_trust = 3
        character.add_item("star_key")
        game.state = GameState(
            character,
            chapter=1,
            scene="complete",
            ending="fellowship",
            flags={
                "part_one_complete": True,
                "defeated_ghorak": True,
                "ned_survived": True,
                "mara_chose_to_continue": True,
                "tobin_chose_to_continue": True,
            },
            play_minutes=play_minutes,
        )
        return game, combat

    def _assert_no_rider_damage_claim(self, transcript: str) -> None:
        lowered = transcript.lower()
        for false_claim in (
            "damage to black rider",
            "black rider falls",
            "black rider is staggered",
            "black rider is defeated",
            "black rider is wounded",
            "black rider crashes",
            "wounds black rider",
            "you strike black rider",
        ):
            self.assertNotIn(false_claim, lowered)


if __name__ == "__main__":
    unittest.main()
