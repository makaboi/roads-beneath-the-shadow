"""Departures preserve their motives without inventing a traversable return road."""

import random
import tempfile
import unittest
from pathlib import Path

from roads_beneath_shadow.combat import CombatDifficulty, CombatEngine, CombatResult
from roads_beneath_shadow.content import ORIGINS
from roads_beneath_shadow.models import Character, GameState
from roads_beneath_shadow.part_two import PartTwoEpisode, part_two_ending_breakdown
from roads_beneath_shadow.savegame import SaveManager
from roads_beneath_shadow.ui import TerminalUI


class CompanionDepartureTests(unittest.TestCase):
    def test_mara_leaves_for_the_prisoners_after_real_troll_collapse_without_claiming_a_return_route(self):
        for victory in (True, False):
            with self.subTest(victory=victory), tempfile.TemporaryDirectory() as directory:
                output = []
                ui = TerminalUI(color=False, fast=True, output_fn=output.append)
                action = "Attack" if victory else "Defend"
                ui.choose = lambda _heading, options, **_: next(index + 1 for index, option in enumerate(options) if option.startswith(action))
                engine = CombatEngine(ui, random.Random(17), CombatDifficulty.STORY if victory else CombatDifficulty.HARD)
                choices = iter((1, 3, 2, 2))  # Strip armor, collapse, leave the shackle, service passage.
                outcomes = []

                def combat(*args):
                    outcomes.append(engine.run(*args))
                    return outcomes[-1]

                episode = PartTwoEpisode(ui, lambda *_: next(choices), combat)
                character = Character.from_origin("Arin", ORIGINS[1])
                character.mara_trust = -2
                if not victory:
                    character.hp = 1
                state = GameState(character, scene="part2_chain_troll", chapter=2,
                                  flags={"part_two_mara_present": True, "part_two_tobin_present": False})

                self.assertTrue(episode.run_scene(state))
                self.assertEqual(outcomes, [CombatResult.VICTORY if victory else CombatResult.DEFEAT])
                self.assertTrue(state.flags["part2_drowned_branch_collapsed"])
                self.assertEqual(state.scene, "part2_house_under_ash")
                saves = SaveManager(Path(directory))
                saves.save(1, state)
                state = saves.load(1)
                before = state.character.__dict__.copy()
                before_minutes = state.play_minutes

                self.assertTrue(episode.run_scene(state))

                self.assertTrue(state.flags["part2_mara_left"])
                self.assertFalse(state.flags["part_two_mara_present"])
                self.assertTrue(state.flags["part2_drowned_branch_collapsed"])
                self.assertFalse(state.flags.get("part2_prisoners_rescued", False))
                self.assertEqual(state.character.mara_trust, before["mara_trust"] - 1)
                self.assertEqual(state.character.hp, before["hp"])
                self.assertEqual((state.scene, state.play_minutes), ("part2_burning_memory", before_minutes + 6))
                prose = " ".join(" ".join(output).split())
                self.assertIn("The flooded passage folds behind you", prose)
                self.assertIn("intent on finding the prisoners", prose)
                self.assertNotIn("turn back toward the prisoners' road", prose)
                self.assertIn("Mara left at the burned refuge", dict(part_two_ending_breakdown(state))["Mara"])


if __name__ == "__main__":
    unittest.main()
